"""Cash-load forecast (PRD §3.3, SCAFFOLD §1.3 cash_load_forecast).

Two variants share the outer shape:
  raw_cents      = avg_daily_dispense_cents * days_until_next_visit * 1.25
  forecast_cents = ceil(raw_cents / note_denomination_cents) * note_denomination_cents

avg_daily_dispense_cents is an integer (floored division), reported as-is.

FORWARD:        sum of WITHDRAWAL amount_cents with created_at in the half-open
                window [now - 14*86400s, now), divided by the FIXED divisor 14.
CHRONOLOGICAL:  sum of WITHDRAWAL amount_cents posted at/after the most recent
                LOADED confirm-load timestamp, divided by
                days_elapsed = max(1, floor((now - last_load_at)/86400)).
                If the ATM has never been LOADED, falls back to FORWARD.
"""
import math
from datetime import timedelta

from constants import (
    FORWARD_WINDOW_DAYS,
    SAFETY_FACTOR_DEN,
    SAFETY_FACTOR_NUM,
    SECONDS_PER_DAY,
)
from util import parse_iso


def _withdrawals_for(store, atm_id):
    return [
        t for t in store.transactions.values()
        if t["atm_id"] == atm_id and t["kind"] == "WITHDRAWAL"
    ]


def _forward_avg(store, atm):
    now = store.clock.get()
    window_start = now - timedelta(days=FORWARD_WINDOW_DAYS)
    total = 0
    for t in _withdrawals_for(store, atm["id"]):
        created = parse_iso(t["created_at"])
        if window_start <= created < now:
            total += t["amount_cents"]
    # Fixed divisor 14, floored.
    return total // FORWARD_WINDOW_DAYS


def _chronological_avg(store, atm):
    last_load_at = atm.get("last_confirm_load_at")
    if not last_load_at:
        # Never LOADED -> fall back to forward.
        return _forward_avg(store, atm)
    load_dt = parse_iso(last_load_at)
    now = store.clock.get()
    total = 0
    for t in _withdrawals_for(store, atm["id"]):
        created = parse_iso(t["created_at"])
        if created >= load_dt:
            total += t["amount_cents"]
    elapsed_seconds = (now - load_dt).total_seconds()
    days_elapsed = max(1, int(elapsed_seconds // SECONDS_PER_DAY))
    return total // days_elapsed


def compute(store, atm, basis, days_until_next_visit):
    if basis == "CHRONOLOGICAL":
        avg = _chronological_avg(store, atm)
    else:
        avg = _forward_avg(store, atm)

    # raw = avg * days * (5/4); keep exact integer arithmetic.
    raw = avg * days_until_next_visit * SAFETY_FACTOR_NUM // SAFETY_FACTOR_DEN
    note = atm["note_denomination_cents"]
    if note <= 0:
        forecast = raw
    else:
        forecast = math.ceil(raw / note) * note
    return {
        "forecast_cents": int(forecast),
        "avg_daily_dispense_cents": int(avg),
        "basis": basis,
    }
