import customtkinter as ctk
import mnemonic
import requests
import threading
import time
import os
import subprocess
import re
import traceback
from itertools import product
from collections import deque
from tkinter import messagebox
from bip_utils import (
    Bip39SeedGenerator,
    Bip44, Bip49, Bip84,
    Bip44Coins, Bip49Coins, Bip84Coins,
    Bip44Changes
)

ctk.set_appearance_mode("dark")

BG_COLOR = "#0a0a0a"
SIDEBAR_BG = "#0d0d0d"
CARD_BG = "#161616"
ACCENT_RED = "#ff1a1a"
ACCENT_RED_HOVER = "#ff3333"
ACCENT_DARK_RED = "#990000"
TEXT_GRAY = "#999999"
SUCCESS_GREEN = "#00ff88"
WARNING_ORANGE = "#ffaa00"

DIAG_LOG = "hunter_diag.log"


class WalletApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("KALI WALLET HUNTER")
        # адаптивный размер
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1380, max(1100, sw - 80))
        h = min(940, max(720, sh - 80))
        self.geometry(f"{w}x{h}")
        self.minsize(min(1100, sw - 40), min(700, sh - 40))
        self.configure(fg_color=BG_COLOR)

        self.mnemo = mnemonic.Mnemonic("english")
        self.wordlist = self.mnemo.wordlist

        self.is_running = False
        self._closing = False
        self._finish_called = False
        self._finish_lock = threading.Lock()
        self.stop_event = threading.Event()
        self._worker_thread = None

        self.checked = 0
        self.found = 0
        self.total = 0
        self.errors = 0
        self.start_time = 0.0
        self._lock = threading.Lock()
        self._min_api_interval = 0.35
        self._last_api_call = 0.0
        self._api_lock = threading.Lock()

        self._save_queue = deque()
        self._save_dialog_open = False
        self._saved_keys = set()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_ui()
        self.run_self_tests()

    def diag(self, msg, exc=None):
        """Диагностический лог без секретов"""
        try:
            with open(DIAG_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
                if exc is not None:
                    f.write(traceback.format_exc())
                    f.write("\n")
        except Exception:
            pass

    def create_ui(self):
        left = ctk.CTkFrame(self, width=400, fg_color=SIDEBAR_BG, corner_radius=0)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="⚔ KALI HUNTER", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=ACCENT_RED).pack(pady=(18, 2))
        ctk.CTkLabel(left, text="STABLE", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_GRAY).pack(pady=(0, 8))
        ctk.CTkFrame(left, height=2, fg_color=ACCENT_RED).pack(fill="x", padx=25, pady=6)

        self._label(left, "МОНЕТА")
        self.coin_var = ctk.StringVar(value="BTC")
        ctk.CTkOptionMenu(left, values=["BTC", "LTC", "DOGE", "ALL"], variable=self.coin_var,
                          fg_color="#1a1a1a", button_color=ACCENT_DARK_RED,
                          button_hover_color=ACCENT_RED, height=32).pack(fill="x", padx=22, pady=3)

        self._label(left, "РЕЖИМ")
        self.mode = ctk.CTkOptionMenu(left, values=[
            "Случайный перебор",
            "Частичная мнемоника",
            "По адресу + частичная фраза",
            "Проверить полную фразу",
            "Проверить фразу на адрес",
            "Проверить баланс адреса"
        ], fg_color="#1a1a1a", button_color=ACCENT_DARK_RED, button_hover_color=ACCENT_RED, height=32,
           command=self._on_mode_change)
        self.mode.pack(fill="x", padx=22, pady=3)
        self.mode.set("Проверить полную фразу")

        self._label(left, "ДЛИНА ФРАЗЫ")
        self.length_var = ctk.StringVar(value="12")
        ctk.CTkOptionMenu(left, values=["12", "24"], variable=self.length_var,
                          fg_color="#1a1a1a", button_color=ACCENT_DARK_RED,
                          button_hover_color=ACCENT_RED, height=32).pack(fill="x", padx=22, pady=3)

        self.count_label = ctk.CTkLabel(left, text="КОЛИЧЕСТВО (случайный режим)", anchor="w",
                                        font=ctk.CTkFont(size=11, weight="bold"), text_color=ACCENT_RED)
        self.count_label.pack(fill="x", padx=22, pady=(8, 2))
        self.count_entry = ctk.CTkEntry(left, fg_color="#141414", border_color=ACCENT_DARK_RED, height=32)
        self.count_entry.pack(fill="x", padx=22, pady=3)
        self.count_entry.insert(0, "50")

        self._label(left, "СКОРОСТЬ (задержка)")
        self.speed_slider = ctk.CTkSlider(left, from_=0.05, to=1.5, number_of_steps=29,
                                          progress_color=ACCENT_RED, button_color=ACCENT_RED,
                                          button_hover_color=ACCENT_RED_HOVER)
        self.speed_slider.set(0.25)
        self.speed_slider.pack(fill="x", padx=22, pady=3)
        self.speed_val = ctk.CTkLabel(left, text="0.25 сек", text_color=TEXT_GRAY)
        self.speed_val.pack()
        self.speed_slider.configure(command=lambda v: self.speed_val.configure(text=f"{float(v):.2f} сек"))

        self._label(left, "PASSPHRASE")
        self.pass_entry = ctk.CTkEntry(left, placeholder_text="если есть (пробелы значимы)", show="*",
                                       fg_color="#141414", border_color=ACCENT_DARK_RED, height=32)
        self.pass_entry.pack(fill="x", padx=22, pady=3)

        self._label(left, "ЧАСТИЧНАЯ / ПОЛНАЯ ФРАЗА")
        self.partial_entry = ctk.CTkEntry(left, placeholder_text="слова через пробел",
                                          fg_color="#141414", border_color=ACCENT_DARK_RED, height=32)
        self.partial_entry.pack(fill="x", padx=22, pady=3)

        self._label(left, "ЦЕЛЕВОЙ АДРЕС")
        self.address_entry = ctk.CTkEntry(left, placeholder_text="1... / 3... / bc1q...",
                                          fg_color="#141414", border_color=ACCENT_DARK_RED, height=32)
        self.address_entry.pack(fill="x", padx=22, pady=3)
        self.address_entry.bind("<Control-v>", self.paste_text)
        self.address_entry.bind("<Button-3>", self.paste_text)

        self._label(left, "ПОЗИЦИИ ПРОПУЩЕННЫХ СЛОВ")
        self.positions_entry = ctk.CTkEntry(left, placeholder_text="например: 3,7,11",
                                            fg_color="#141414", border_color=ACCENT_DARK_RED, height=32)
        self.positions_entry.pack(fill="x", padx=22, pady=3)

        self.start_btn = ctk.CTkButton(left, text="⚡  ЗАПУСТИТЬ", fg_color=ACCENT_RED,
                                       hover_color=ACCENT_RED_HOVER, height=46,
                                       font=ctk.CTkFont(size=15, weight="bold"),
                                       command=self.start_search)
        self.start_btn.pack(fill="x", padx=22, pady=(14, 5))

        self.stop_btn = ctk.CTkButton(left, text="⏹  СТОП", fg_color="#2a0000",
                                      hover_color="#440000", height=38, state="disabled",
                                      command=self.stop_search)
        self.stop_btn.pack(fill="x", padx=22, pady=4)

        ctk.CTkButton(left, text="📁  Результаты", height=34, fg_color="#1a1a1a",
                      hover_color="#222", border_color=ACCENT_DARK_RED, border_width=1,
                      command=self.open_results).pack(fill="x", padx=22, pady=(8, 3))
        ctk.CTkButton(left, text="🗑  Очистить лог", height=32, fg_color="#1a1a1a",
                      hover_color="#222", command=self.clear_log).pack(fill="x", padx=22, pady=3)

        right = ctk.CTkFrame(self, fg_color=BG_COLOR)
        right.pack(side="right", fill="both", expand=True)

        self.tabview = ctk.CTkTabview(right, fg_color=BG_COLOR,
                                      segmented_button_fg_color="#1a1a1a",
                                      segmented_button_selected_color=ACCENT_DARK_RED,
                                      segmented_button_selected_hover_color=ACCENT_RED,
                                      segmented_button_unselected_color="#111")
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_log = self.tabview.add("⚔ ХОД РАБОТЫ")
        self.tab_found = self.tabview.add("💰 НАЙДЕННЫЕ")
        self.tab_balance = self.tabview.add("🔍 БАЛАНС")

        stats = ctk.CTkFrame(self.tab_log, fg_color=CARD_BG)
        stats.pack(fill="x", padx=6, pady=6)

        self.checked_label = ctk.CTkLabel(stats, text="Проверено: 0", font=ctk.CTkFont(size=14))
        self.checked_label.pack(side="left", padx=12, pady=8)
        self.found_label = ctk.CTkLabel(stats, text="Найдено: 0", font=ctk.CTkFont(size=14), text_color=SUCCESS_GREEN)
        self.found_label.pack(side="left", padx=12, pady=8)
        self.errors_label = ctk.CTkLabel(stats, text="Ошибки: 0", font=ctk.CTkFont(size=14), text_color=WARNING_ORANGE)
        self.errors_label.pack(side="left", padx=12, pady=8)
        self.speed_label = ctk.CTkLabel(stats, text="Скорость: 0.00/сек", font=ctk.CTkFont(size=14))
        self.speed_label.pack(side="left", padx=12, pady=8)
        self.status_label = ctk.CTkLabel(stats, text="● ОЖИДАНИЕ", font=ctk.CTkFont(size=14, weight="bold"),
                                         text_color=ACCENT_RED)
        self.status_label.pack(side="right", padx=12, pady=8)

        self.progress = ctk.CTkProgressBar(self.tab_log, progress_color=ACCENT_RED, fg_color="#222", height=12)
        self.progress.pack(fill="x", padx=8, pady=(2, 2))
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(self.tab_log, text="0 / 0", text_color=TEXT_GRAY)
        self.progress_label.pack(pady=(0, 4))

        self.log = ctk.CTkTextbox(self.tab_log, fg_color="#0a0a0a", text_color="#00ff88",
                                  font=ctk.CTkFont(family="monospace", size=13),
                                  border_color=ACCENT_DARK_RED, border_width=1)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.found_frame = ctk.CTkScrollableFrame(self.tab_found, fg_color=BG_COLOR)
        self.found_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.no_found_label = ctk.CTkLabel(self.found_frame, text="Пока ничего не найдено", text_color=TEXT_GRAY)
        self.no_found_label.pack(pady=40)

        bal_card = ctk.CTkFrame(self.tab_balance, fg_color=CARD_BG, border_color=ACCENT_RED, border_width=1)
        bal_card.pack(pady=50, padx=40)

        ctk.CTkLabel(
            bal_card,
            text="🔍 ПРОВЕРКА БАЛАНСА",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=ACCENT_RED
        ).pack(pady=(22, 14))

        self.bal_address_entry = ctk.CTkEntry(bal_card, width=560, height=42,
                                              placeholder_text="Вставь адрес и нажми Enter",
                                              fg_color="#111", border_color=ACCENT_RED)
        self.bal_address_entry.pack(pady=8, padx=25)
        self.bal_address_entry.bind("<Control-v>", self.paste_text)
        self.bal_address_entry.bind("<Button-3>", self.paste_text)
        self.bal_address_entry.bind("<Return>", lambda e: self.start_balance_check())

        ctk.CTkButton(bal_card, text="ПРОВЕРИТЬ БАЛАНС", fg_color=ACCENT_RED,
                      hover_color=ACCENT_RED_HOVER, height=42,
                      command=self.start_balance_check).pack(pady=12)
        self.bal_result_label = ctk.CTkLabel(bal_card, text="", font=ctk.CTkFont(size=22, weight="bold"))
        self.bal_result_label.pack(pady=(8, 25))

        self._on_mode_change(self.mode.get())

    def _label(self, parent, text):
        ctk.CTkLabel(parent, text=text, anchor="w", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=ACCENT_RED).pack(fill="x", padx=22, pady=(8, 2))

    def _on_mode_change(self, value=None):
        mode = value or self.mode.get()
        if mode == "Случайный перебор":
            self.count_label.configure(text="КОЛИЧЕСТВО ФРАЗ (случайный режим)")
            try:
                self.count_entry.configure(state="normal")
            except Exception:
                pass
        else:
            self.count_label.configure(text="КОЛИЧЕСТВО (не используется в этом режиме)")
            try:
                self.count_entry.configure(state="disabled")
            except Exception:
                pass

    def paste_text(self, event=None):
        try:
            text = self.clipboard_get().strip()
            if event and event.widget:
                event.widget.delete(0, "end")
                event.widget.insert(0, text)
        except Exception:
            pass
        return "break"

    def get_entry_text(self, entry):
        try:
            return entry.get().strip()
        except Exception:
            return ""

    def get_passphrase(self):
        try:
            return self.pass_entry.get()
        except Exception:
            return ""

    def log_message(self, text):
        if self._closing:
            return
        def _log():
            try:
                if not self._closing:
                    self.log.insert("end", text + "\n")
                    self.log.see("end")
            except Exception:
                pass
        try:
            self.after(0, _log)
        except Exception:
            pass

    def clear_log(self):
        try:
            self.log.delete("1.0", "end")
        except Exception:
            pass

    def update_stats(self):
        if self._closing:
            return
        def _u():
            try:
                if self._closing:
                    return
                with self._lock:
                    checked = self.checked
                    found = self.found
                    total = self.total
                    errors = self.errors
                    start = self.start_time
                self.checked_label.configure(text=f"Проверено: {checked}")
                self.found_label.configure(text=f"Найдено: {found}")
                self.errors_label.configure(text=f"Ошибки: {errors}")
                elapsed = max(time.time() - start, 0.001)
                self.speed_label.configure(text=f"Скорость: {checked / elapsed:.2f}/сек")
                if total > 0:
                    pct = min(checked / total, 1.0)
                    self.progress.set(pct)
                    self.progress_label.configure(text=f"{checked} / {total}  ({pct * 100:.1f}%)")
                else:
                    self.progress_label.configure(text=str(checked))
            except Exception:
                pass
        try:
            self.after(0, _u)
        except Exception:
            pass

    def set_status(self, text, color=ACCENT_RED):
        if self._closing:
            return
        def _s():
            try:
                if not self._closing:
                    self.status_label.configure(text=text, text_color=color)
            except Exception:
                pass
        try:
            self.after(0, _s)
        except Exception:
            pass

    def clear_found(self):
        def _c():
            try:
                for w in self.found_frame.winfo_children():
                    w.destroy()
                self.no_found_label = ctk.CTkLabel(self.found_frame, text="Пока ничего не найдено", text_color=TEXT_GRAY)
                self.no_found_label.pack(pady=40)
            except Exception:
                pass
        try:
            self.after(0, _c)
        except Exception:
            pass

    def add_found_card(self, short_info, addr, bal, path, coin, has_passphrase=False):
        def _a():
            try:
                if self._closing:
                    return
                if hasattr(self, "no_found_label") and self.no_found_label.winfo_exists():
                    self.no_found_label.destroy()
                card = ctk.CTkFrame(self.found_frame, fg_color=CARD_BG, border_color=ACCENT_RED, border_width=1)
                card.pack(fill="x", pady=7, padx=8)
                ctk.CTkLabel(card, text=f"💰 {bal} {coin}", font=ctk.CTkFont(size=18, weight="bold"),
                             text_color=SUCCESS_GREEN).pack(anchor="w", padx=15, pady=(12, 3))
                ctk.CTkLabel(card, text=f"Адрес: {addr}", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=15)
                ctk.CTkLabel(card, text=f"Путь: {path}", font=ctk.CTkFont(size=12), text_color=TEXT_GRAY).pack(anchor="w", padx=15)
                pp = "Passphrase: задана" if has_passphrase else "Passphrase: не задана"
                ctk.CTkLabel(card, text=pp, font=ctk.CTkFont(size=12), text_color=TEXT_GRAY).pack(anchor="w", padx=15)
                ctk.CTkLabel(card, text=f"Инфо: {short_info}", font=ctk.CTkFont(size=12), text_color="#ff5555").pack(anchor="w", padx=15, pady=(3, 12))
            except Exception:
                pass
        try:
            self.after(0, _a)
        except Exception:
            pass

    def _interruptible_sleep(self, seconds):
        if seconds <= 0:
            return
        self.stop_event.wait(timeout=seconds)

    def _rate_limit(self):
        with self._api_lock:
            now = time.time()
            elapsed = now - self._last_api_call
            wait = self._min_api_interval - elapsed
            if wait > 0:
                self.stop_event.wait(timeout=wait)
            self._last_api_call = time.time()

    def _new_session(self):
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        })
        return s

    def _should_stop(self):
        return self.stop_event.is_set() or self._closing or not self.is_running

    def _inc_checked(self, n=1):
        with self._lock:
            self.checked += n

    def _inc_found(self, n=1):
        with self._lock:
            self.found += n

    def _inc_errors(self, n=1):
        with self._lock:
            self.errors += n

    def validate_address(self, address, coin):
        if not address:
            return False, "пустой адрес"
        a = address.strip()
        if coin == "BTC":
            if re.match(r"^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$", a):
                return True, "ok"
            if re.match(r"^bc1[a-z0-9]{14,90}$", a, re.IGNORECASE):
                return True, "ok"
            return False, "не похоже на BTC-адрес"
        if coin == "LTC":
            if re.match(r"^(L|M)[a-km-zA-HJ-NP-Z1-9]{25,34}$", a):
                return True, "ok"
            if re.match(r"^ltc1[a-z0-9]{14,90}$", a, re.IGNORECASE):
                return True, "ok"
            return False, "не похоже на LTC-адрес"
        if coin == "DOGE":
            if re.match(r"^D[a-km-zA-HJ-NP-Z1-9]{25,34}$", a):
                return True, "ok"
            return False, "не похоже на DOGE-адрес"
        return True, "ok"

    def start_search(self):
        if self.is_running or self._closing:
            return

        mode = self.mode.get()
        if mode == "Проверить баланс адреса":
            self.start_balance_check()
            return

        try:
            length = int(self.length_var.get())
            count = int(self.get_entry_text(self.count_entry) or "50")
            if not (1 <= count <= 100000):
                raise ValueError("1–100000")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Некорректное количество: {e}")
            return

        passphrase = self.get_passphrase()
        partial = self.get_entry_text(self.partial_entry)
        address = self.get_entry_text(self.address_entry)
        positions_raw = self.get_entry_text(self.positions_entry)
        coin = self.coin_var.get()
        delay = float(self.speed_slider.get())

        if mode == "Случайный перебор":
            if not messagebox.askyesno("Внимание", "Случайный перебор имеет почти нулевой шанс.\nВсё равно запустить?"):
                return

        if mode in ("По адресу + частичная фраза", "Проверить фразу на адрес") and not address:
            messagebox.showerror("Ошибка", "Укажите целевой адрес")
            return
        if mode in ("Частичная мнемоника", "По адресу + частичная фраза") and not partial:
            messagebox.showerror("Ошибка", "Укажите частичную фразу")
            return
        if mode in ("Проверить полную фразу", "Проверить фразу на адрес") and not partial:
            messagebox.showerror("Ошибка", "Укажите фразу")
            return

        if address and coin in ("BTC", "LTC", "DOGE"):
            ok, msg = self.validate_address(address, coin)
            if not ok:
                if not messagebox.askyesno("Адрес", f"Предупреждение: {msg}.\nПродолжить всё равно?"):
                    return

        if mode in ("Частичная мнемоника", "По адресу + частичная фраза"):
            words = partial.split()
            missing = length - len(words)
            if missing >= 2:
                approx = 2048 ** missing
                if not messagebox.askyesno("Долгий перебор", f"Примерно {approx:,} вариантов.\nПродолжить?"):
                    return

        total = count if mode == "Случайный перебор" else 0
        self._prepare_run(total=total)
        self.log_message(f"⚔ Старт → {mode} | {coin}")

        self._worker_thread = threading.Thread(
            target=self.worker,
            args=(mode, length, count, passphrase, partial, address, positions_raw, coin, delay),
            daemon=True
        )
        self._worker_thread.start()

    def start_balance_check(self):
        if self.is_running or self._closing:
            return

        addr = self.get_entry_text(self.bal_address_entry) or self.get_entry_text(self.address_entry)
        coin = self.coin_var.get()
        if coin == "ALL":
            coin = "BTC"

        if not addr:
            try:
                self.bal_result_label.configure(text="Введите адрес", text_color=WARNING_ORANGE)
            except Exception:
                pass
            return

        ok, msg = self.validate_address(addr, coin)
        if not ok:
            try:
                self.bal_result_label.configure(text=f"Формат: {msg}", text_color=WARNING_ORANGE)
            except Exception:
                pass
            self.log_message(f"⚠ Адрес: {msg}")

        self._prepare_run(total=0)
        try:
            self.bal_result_label.configure(text="Проверяю...", text_color="white")
        except Exception:
            pass
        self.set_status("● ПРОВЕРКА")
        self.log_message(f"🔍 Проверка баланса ({coin})")

        def worker():
            session = self._new_session()
            try:
                if self._should_stop():
                    return
                bal, status = self.get_balance(addr, coin, session=session)

                def ui():
                    if self._closing:
                        return
                    try:
                        if status == "ok":
                            color = SUCCESS_GREEN if bal > 0 else "white"
                            self.bal_result_label.configure(text=f"{bal} {coin}", text_color=color)
                            self.log_message(f"Баланс → {bal} {coin} [ok]")
                        else:
                            self.bal_result_label.configure(text=f"Ошибка: {status}", text_color=WARNING_ORANGE)
                            self.log_message(f"Баланс → ошибка [{status}]")
                            self._inc_errors()
                            self.update_stats()
                    except Exception:
                        pass

                try:
                    self.after(0, ui)
                except Exception:
                    pass
            except Exception as e:
                self.log_message(f"❌ Ошибка проверки баланса: {type(e).__name__}")
                self.diag("balance_check", e)
            finally:
                try:
                    session.close()
                except Exception:
                    pass
                self.finish()

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _prepare_run(self, total=0):
        self.is_running = True
        self.stop_event.clear()
        with self._finish_lock:
            self._finish_called = False
        with self._lock:
            self.checked = 0
            self.found = 0
            self.errors = 0
            self.total = total
            self.start_time = time.time()
        try:
            self.progress.set(0)
        except Exception:
            pass
        self.clear_found()
        self.update_stats()
        try:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        except Exception:
            pass
        self.set_status("● РАБОТА")

    def stop_search(self):
        self.stop_event.set()
        self.is_running = False
        self.set_status("● ОСТАНОВКА...", WARNING_ORANGE)
        self.log_message("⏹ Остановка...")

    def finish(self):
        with self._finish_lock:
            if self._finish_called:
                return
            self._finish_called = True
        self.is_running = False
        self.stop_event.set()
        if self._closing:
            return

        def _restore():
            try:
                if not self._closing:
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
            except Exception:
                pass

        try:
            self.after(0, _restore)
        except Exception:
            pass
        self.set_status("● ОЖИДАНИЕ")
        self.log_message("——— ЗАВЕРШЕНО ———\n")

    def on_closing(self):
        self._closing = True
        self.is_running = False
        self.stop_event.set()
        # не ждём worker долго — daemon завершится с процессом
        try:
            self.destroy()
        except Exception:
            pass

    def worker(self, mode, length, count, passphrase, partial, address, positions_raw, coin, delay):
        session = self._new_session()
        try:
            if mode == "Случайный перебор":
                self.random_search(count, length, passphrase, coin, delay, session)
            elif mode == "Частичная мнемоника":
                self.recover_partial(partial, length, None, passphrase, positions_raw, coin, delay, session)
            elif mode == "По адресу + частичная фраза":
                self.recover_partial(partial, length, address, passphrase, positions_raw, coin, delay, session)
            elif mode == "Проверить полную фразу":
                if self.is_valid(partial):
                    self.check_full(partial, passphrase, coin, session)
                else:
                    self.log_message("❌ Невалидная фраза")
            elif mode == "Проверить фразу на адрес":
                if self.is_valid(partial):
                    self.check_phrase_against_address(partial, address, passphrase, coin, session)
                else:
                    self.log_message("❌ Невалидная фраза")
        except Exception as e:
            self.log_message(f"❌ Ошибка воркера: {type(e).__name__}")
            self.diag("worker", e)
            self._inc_errors()
            self.update_stats()
        finally:
            try:
                session.close()
            except Exception:
                pass
            self.finish()

    def random_search(self, count, length, passphrase, coin, delay, session):
        self.log_message(f"▶ Случайный перебор ({count})")
        while not self._should_stop():
            with self._lock:
                if self.checked >= count:
                    break
            phrase = self.mnemo.generate(strength=128 if length == 12 else 256)
            self._inc_checked()
            with self._lock:
                current = self.checked
            self.log_message(f"[{current}/{count}] проверка...")
            if self.check_one(phrase, passphrase, coin, delay, session):
                self._inc_found()
            self.update_stats()
            self._interruptible_sleep(0.01)

    def check_one(self, phrase, passphrase, coin, delay, session):
        coins = ["BTC"] if coin == "BTC" else (["BTC", "LTC", "DOGE"] if coin == "ALL" else [coin])
        found_any = False
        for c in coins:
            if self._should_stop():
                break
            paths = self.derive_all(phrase, passphrase, c)
            if paths is None:
                self._inc_errors()
                continue
            for path, addr in paths:
                if self._should_stop():
                    break
                bal, status = self.get_balance(addr, c, session=session)
                if status != "ok":
                    self._inc_errors()
                self.log_message(f"    {c} | {path} | {addr[:20]}... | {bal} [{status}]")
                if status == "ok" and bal > 0:
                    self.ask_and_save(phrase, addr, bal, path, passphrase, c, status=status)
                    found_any = True
                self._interruptible_sleep(delay)
        return found_any

    def check_full(self, phrase, passphrase, coin, session):
        self.log_message("▶ Проверка полной фразы")
        coins = ["BTC"] if coin == "BTC" else (["BTC", "LTC", "DOGE"] if coin == "ALL" else [coin])
        any_balance = False
        for c in coins:
            if self._should_stop():
                break
            self.log_message(f"  --- {c} ---")
            paths = self.derive_all(phrase, passphrase, c)
            if paths is None:
                self._inc_errors()
                self.update_stats()
                continue
            for path, addr in paths:
                if self._should_stop():
                    break
                bal, status = self.get_balance(addr, c, session=session)
                self._inc_checked()
                if status != "ok":
                    self._inc_errors()
                mark = "💰" if (status == "ok" and bal > 0) else "  "
                self.log_message(f"  {mark} {path} | {addr} | {bal} [{status}]")
                if status == "ok" and bal > 0:
                    any_balance = True
                    self._inc_found()
                    self.ask_and_save(phrase, addr, bal, path, passphrase, c, status=status)
                self.update_stats()
        if not any_balance:
            self.log_message("  Балансов > 0 не найдено")

    def check_phrase_against_address(self, phrase, target, passphrase, coin, session):
        self.log_message("▶ Проверка фразы на адрес")
        target_n = target.strip()
        coins = ["BTC"] if coin == "BTC" else (["BTC", "LTC", "DOGE"] if coin == "ALL" else [coin])
        matches = []
        for c in coins:
            paths = self.derive_all(phrase, passphrase, c)
            if paths is None:
                self._inc_errors()
                continue
            for path, addr in paths:
                if addr and self._addr_equal(addr, target_n):
                    matches.append((c, path, addr))
        if not matches:
            self.log_message("❌ Адрес не найден среди путей этой фразы")
            return
        self.log_message(f"✅ Совпадений адреса: {len(matches)}")
        for c, path, addr in matches:
            if self._should_stop():
                break
            bal, status = self.get_balance(addr, c, session=session)
            self._inc_checked()
            if status != "ok":
                self._inc_errors()
                self.log_message(f"  {c} | {path} | {addr} | API: {status}")
                self.log_message("  ℹ Совпадение деривации подтверждено, баланс не получен")
            else:
                if bal > 0:
                    self._inc_found()
                self.log_message(f"  {c} | {path} | {addr} | {bal} [ok]")
                self.ask_and_save(phrase, addr, bal, path, passphrase, c, status=status)
            self.update_stats()

    def recover_partial(self, partial, length, target, passphrase, positions_raw, coin, delay, session):
        words = partial.split()
        missing = length - len(words)
        if missing < 1 or missing > 3:
            self.log_message("❌ Можно восстанавливать только 1–3 слова")
            return

        positions = None
        if missing >= 2:
            if not positions_raw:
                self.log_message("❌ Укажите позиции (например: 3,7,11)")
                return
            try:
                positions = [int(x.strip()) - 1 for x in positions_raw.split(",")]
                if len(positions) != missing or len(set(positions)) != len(positions):
                    self.log_message("❌ Некорректные позиции")
                    return
                if any(p < 0 or p >= length for p in positions):
                    self.log_message("❌ Позиция вне диапазона")
                    return
                positions = sorted(positions, reverse=True)
            except Exception:
                self.log_message("❌ Ошибка позиций")
                return

        self.log_message(f"▶ Восстановление {missing} слов")

        if missing == 1:
            with self._lock:
                self.total = length * 2048
            self.log_message(f"  Объём перебора: {self.total} (включая невалидные BIP39)")
            for pos in range(length):
                if self._should_stop():
                    return
                for w in self.wordlist:
                    if self._should_stop():
                        return
                    test = words[:]
                    test.insert(pos, w)
                    phrase = " ".join(test)
                    self._inc_checked()
                    if len(test) != length or not self.is_valid(phrase):
                        self.update_stats()
                        continue
                    self.log_message(f"  Валидный (поз.{pos + 1})")
                    if target:
                        matched = self.check_against_address(phrase, target, passphrase, coin, session)
                        if matched:
                            self._inc_found()
                            self.update_stats()
                            return
                    else:
                        self.check_full(phrase, passphrase, coin, session)
                    self.update_stats()
                    self._interruptible_sleep(delay * 0.08)
        else:
            approx = 2048 ** missing
            with self._lock:
                self.total = approx
            self.log_message(f"  Объём перебора ≈ {approx}")
            for combo in product(self.wordlist, repeat=missing):
                if self._should_stop():
                    return
                test = words[:]
                for i, p in enumerate(positions):
                    test.insert(p, combo[i])
                phrase = " ".join(test)
                self._inc_checked()
                if not self.is_valid(phrase):
                    self.update_stats()
                    continue
                self.log_message("  Валидная комбинация")
                if target:
                    matched = self.check_against_address(phrase, target, passphrase, coin, session)
                    if matched:
                        self._inc_found()
                        self.update_stats()
                        return
                else:
                    self.check_full(phrase, passphrase, coin, session)
                self.update_stats()
                self._interruptible_sleep(delay * 0.08)

    def check_against_address(self, phrase, target, passphrase, coin, session):
        coins = ["BTC"] if coin == "BTC" else (["BTC", "LTC", "DOGE"] if coin == "ALL" else [coin])
        target_n = target.strip()
        for c in coins:
            paths = self.derive_all(phrase, passphrase, c)
            if paths is None:
                self._inc_errors()
                continue
            for path, addr in paths:
                if addr and self._addr_equal(addr, target_n):
                    bal, status = self.get_balance(addr, c, session=session)
                    self.log_message("  ✅ Совпадение адреса")
                    if status != "ok":
                        self._inc_errors()
                        self.log_message(f"  ℹ Баланс недоступен [{status}]")
                    else:
                        self.ask_and_save(phrase, addr, bal, path, passphrase, c, status=status)
                    return True
        return False

    def _addr_equal(self, a, b):
        return a.lower() == b.lower()

    def derive_all(self, phrase, passphrase, coin):
        results = []
        try:
            seed_bytes = Bip39SeedGenerator(phrase).Generate(passphrase or "")

            if coin == "BTC":
                ctx = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
                for acc in range(0, 2):
                    for idx in range(0, 3):
                        addr = ctx.Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                        results.append((f"m/84'/0'/{acc}'/0/{idx}", addr))

                ctx = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN)
                for acc in range(0, 2):
                    for idx in range(0, 2):
                        addr = ctx.Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                        results.append((f"m/49'/0'/{acc}'/0/{idx}", addr))

                ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN)
                for acc in range(0, 2):
                    for idx in range(0, 2):
                        addr = ctx.Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                        results.append((f"m/44'/0'/{acc}'/0/{idx}", addr))

            elif coin == "LTC":
                ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN)
                for idx in range(0, 3):
                    addr = ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                    results.append((f"m/44'/2'/0'/0/{idx}", addr))

            elif coin == "DOGE":
                ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.DOGECOIN)
                for idx in range(0, 3):
                    addr = ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                    results.append((f"m/44'/3'/0'/0/{idx}", addr))
            else:
                self.log_message(f"[derive] неизвестная монета: {coin}")
                return None

            if not results:
                self.log_message("[derive] пустой результат")
                return None
            return results

        except Exception as e:
            self.log_message(f"[derive error] {type(e).__name__}")
            self.diag("derive_all", e)
            return None

    def get_balance(self, address, coin="BTC", session=None):
        if self._should_stop() and session is None:
            return 0.0, "network"

        self._rate_limit()
        if self._should_stop():
            return 0.0, "network"

        own_session = session is None
        if own_session:
            session = self._new_session()

        def _parse_btc_style(data):
            try:
                chain = data.get("chain_stats")
                if not isinstance(chain, dict):
                    return None, "parse_error"
                funded = chain.get("funded_txo_sum")
                spent = chain.get("spent_txo_sum")
                if not isinstance(funded, (int, float)) or not isinstance(spent, (int, float)):
                    return None, "parse_error"
                bal = (funded - spent) / 1e8
                if bal < 0:
                    return None, "parse_error"
                return float(bal), "ok"
            except Exception:
                return None, "parse_error"

        try:
            if coin == "BTC":
                sources = [
                    f"https://mempool.space/api/address/{address}",
                    f"https://blockstream.info/api/address/{address}",
                ]
                last_status = "network"
                for url in sources:
                    if self._should_stop():
                        return 0.0, "network"
                    try:
                        r = session.get(url, timeout=8)
                        if r.status_code != 200:
                            last_status = f"http_{r.status_code}"
                            continue
                        data = r.json()
                        bal, status = _parse_btc_style(data)
                        if status == "ok":
                            return bal, "ok"
                        last_status = status
                    except requests.exceptions.Timeout:
                        last_status = "timeout"
                        continue
                    except requests.exceptions.RequestException:
                        last_status = "network"
                        continue
                    except ValueError:
                        last_status = "parse_error"
                        continue
                    except Exception:
                        last_status = "parse_error"
                        continue
                return 0.0, last_status

            if coin == "LTC":
                try:
                    r = session.get(f"https://litecoinspace.org/api/address/{address}", timeout=8)
                    if r.status_code != 200:
                        return 0.0, f"http_{r.status_code}"
                    data = r.json()
                    bal, status = _parse_btc_style(data)
                    return (bal if status == "ok" else 0.0), status
                except requests.exceptions.Timeout:
                    return 0.0, "timeout"
                except requests.exceptions.RequestException:
                    return 0.0, "network"
                except Exception:
                    return 0.0, "parse_error"

            if coin == "DOGE":
                try:
                    r = session.get(f"https://dogechain.com/api/v3/address/{address}", timeout=8)
                    if r.status_code != 200:
                        return 0.0, f"http_{r.status_code}"
                    data = r.json()
                    if data.get("status") != "success":
                        return 0.0, "parse_error"
                    bal = float(data["data"]["summary"]["confirmed_balance"])
                    if bal < 0:
                        return 0.0, "parse_error"
                    return bal, "ok"
                except requests.exceptions.Timeout:
                    return 0.0, "timeout"
                except requests.exceptions.RequestException:
                    return 0.0, "network"
                except Exception:
                    return 0.0, "parse_error"

            return 0.0, "network"

        except Exception as e:
            self.diag("get_balance", e)
            return 0.0, "network"
        finally:
            if own_session:
                try:
                    session.close()
                except Exception:
                    pass

    def ask_and_save(self, phrase, addr, bal, path, passphrase, coin, status="ok"):
        if status != "ok":
            self.log_message("⏭ Сохранение пропущено: ошибка проверки баланса")
            return

        key = (coin, addr, path)
        if key in self._saved_keys:
            self.log_message("⏭ Уже сохранено ранее (дубликат)")
            return

        item = {
            "phrase": phrase,
            "addr": addr,
            "bal": bal,
            "path": path,
            "passphrase": passphrase,
            "coin": coin,
        }
        self._save_queue.append(item)
        try:
            self.after(0, self._process_save_queue)
        except Exception:
            pass

    def _process_save_queue(self):
        if self._closing or self._save_dialog_open:
            return
        if not self._save_queue:
            return

        self._save_dialog_open = True
        item = self._save_queue.popleft()
        phrase = item["phrase"]
        addr = item["addr"]
        bal = item["bal"]
        path = item["path"]
        passphrase = item["passphrase"]
        coin = item["coin"]

        key = (coin, addr, path)
        if key in self._saved_keys:
            self._save_dialog_open = False
            self.log_message("⏭ Уже сохранено ранее (дубликат)")
            self.after(0, self._process_save_queue)
            return

        short = phrase[:6] + "..." + phrase[-6:] if len(phrase) > 14 else "***"
        has_pp = bool(passphrase)

        try:
            ok = messagebox.askyesno(
                "Найден результат",
                f"Баланс: {bal} {coin}\n"
                f"Адрес: {addr}\n\n"
                f"Сохранить seed-фразу и данные в found_wallets.txt?\n"
                f"(файл будет в открытом виде)"
            )
        except Exception:
            self._save_dialog_open = False
            return

        if not ok:
            self.log_message("⏭ Сохранение отменено")
            self._save_dialog_open = False
            self.after(0, self._process_save_queue)
            return

        try:
            with open("found_wallets.txt", "a", encoding="utf-8") as f:
                f.write(f"Coin: {coin}\n")
                f.write(f"Mnemonic: {phrase}\n")
                if passphrase:
                    f.write(f"Passphrase: {passphrase}\n")
                f.write(f"Address: {addr}\n")
                f.write(f"Balance: {bal}\n")
                f.write(f"Path: {path}\n")
                f.write("-" * 50 + "\n")
            try:
                os.chmod("found_wallets.txt", 0o600)
            except Exception:
                pass
            self._saved_keys.add(key)
            self.add_found_card(short, addr, bal, path, coin, has_passphrase=has_pp)
            self.log_message(f"💾 Сохранено ({bal} {coin})")
        except Exception as e:
            self.log_message(f"❌ Ошибка записи: {type(e).__name__}")
            self.diag("save", e)

        self._save_dialog_open = False
        self.after(0, self._process_save_queue)

    def is_valid(self, phrase):
        try:
            return self.mnemo.check(phrase)
        except Exception:
            return False

    def open_results(self):
        path = os.path.abspath("found_wallets.txt")
        if not os.path.exists(path):
            messagebox.showinfo("Инфо", "Файл ещё не создан")
            return
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                messagebox.showinfo("Файл результатов", f"Путь:\n{path}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def run_self_tests(self):
        try:
            test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
            if not self.mnemo.check(test_mnemonic):
                self.log_message("[TEST FAIL] BIP39 checksum")
                return

            results = self.derive_all(test_mnemonic, "", "BTC")
            if results is None:
                self.log_message("[TEST FAIL] BTC derive returned None")
                return
            result_dict = {path: addr for path, addr in results}
            expected_btc = {
                "m/44'/0'/0'/0/0": "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA",
                "m/49'/0'/0'/0/0": "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf",
                "m/84'/0'/0'/0/0": "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
            }
            all_ok = True
            for path, expected_addr in expected_btc.items():
                if result_dict.get(path) != expected_addr:
                    self.log_message(f"[TEST FAIL] BTC {path}")
                    all_ok = False

            ltc_results = self.derive_all(test_mnemonic, "", "LTC")
            if ltc_results is None or not ltc_results[0][1]:
                self.log_message("[TEST FAIL] LTC empty/error")
                all_ok = False

            doge_results = self.derive_all(test_mnemonic, "", "DOGE")
            if doge_results is None or not doge_results[0][1]:
                self.log_message("[TEST FAIL] DOGE empty/error")
                all_ok = False

            if all_ok:
                self.log_message("[TEST OK] BIP39 + BIP44/49/84 (BTC) + LTC/DOGE derive")
            else:
                self.log_message("[TEST FAIL] Есть ошибки деривации")
        except Exception as e:
            self.log_message(f"[TEST ERROR] {type(e).__name__}")
            self.diag("self_test", e)


if __name__ == "__main__":
    app = WalletApp()
    app.mainloop()
