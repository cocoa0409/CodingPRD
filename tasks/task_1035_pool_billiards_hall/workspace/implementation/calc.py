"""Calculation rules (SCAFFOLD §1.3 / PRD §3.3, §3.4, §3.5, §3.7)."""
from datetime import timedelta
from decimal import Decimal

from common import (
    round_half_up,
    MIN_BILLED_MINUTES,
    PEAK_START_HOUR,
    PEAK_END_HOUR,
    PEAK_MULTIPLIER,
    FNB_TAX_PCT,
    EVENT_TABLE_HOUR_RATE_CENTS,
    EVENT_DEPOSIT_PCT,
    HANDICAP_SPOT_CAP,
)


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def whole_hours(start, end):
    return int((end - start).total_seconds() // 3600)


def provisional_charge(reserved_minutes, hourly_rate_cents):
    """table_session_charge variant=provisional: off-peak flat, no discount."""
    billed = max(reserved_minutes, MIN_BILLED_MINUTES)
    return round_half_up(Decimal(billed * hourly_rate_cents) / Decimal(60))


def final_charge(started_at, ended_at, hourly_rate_cents, discount_pct):
    """table_session_charge variant=final: elapsed time, peak split, member discount."""
    actual = whole_minutes(started_at, ended_at)
    billed = max(actual, MIN_BILLED_MINUTES)
    peak_min = 0
    for i in range(billed):
        minute_start = started_at + timedelta(minutes=i)
        hour = minute_start.astimezone(started_at.tzinfo).hour
        if PEAK_START_HOUR <= hour < PEAK_END_HOUR:
            peak_min += 1
    offpeak_min = billed - peak_min
    per_minute = Decimal(hourly_rate_cents) / Decimal(60)
    gross = offpeak_min * per_minute + peak_min * per_minute * PEAK_MULTIPLIER
    discount = Decimal(str(discount_pct)) if discount_pct else Decimal(0)
    return round_half_up(gross * (Decimal(1) - discount))


def fnb_totals(line_items):
    """fnb_order_total: subtotal, per-line rounded tax summed, total."""
    subtotal = 0
    tax = 0
    for li in line_items:
        line = li["unit_price_cents"] * li["qty"]
        subtotal += line
        tax += round_half_up(Decimal(line) * FNB_TAX_PCT)
    return subtotal, tax, subtotal + tax


def event_quote(table_count, start_at, end_at):
    hours = whole_hours(start_at, end_at)
    base = table_count * hours * EVENT_TABLE_HOUR_RATE_CENTS
    if table_count >= 10:
        bulk = Decimal("0.15")
    elif table_count >= 6:
        bulk = Decimal("0.10")
    elif table_count >= 3:
        bulk = Decimal("0.05")
    else:
        bulk = Decimal("0")
    quote = round_half_up(Decimal(base) * (Decimal(1) - bulk))
    deposit = round_half_up(Decimal(quote) * EVENT_DEPOSIT_PCT)
    return quote, deposit


def handicap_spot(mode, top_rating, player_rating):
    if mode == "NONE":
        return 0
    raw = top_rating - player_rating
    if mode == "FULL":
        return raw
    # CAPPED
    return min(HANDICAP_SPOT_CAP, raw)
