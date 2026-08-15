"""work_order_quote and sla_turnaround_window (PRD §3.2).

Quote evaluation order is pinned: duration charge across marginal brackets,
then tier multiplier (rounded half-up to a whole cent), then the volume
discount read from the client's ytd_completed_minutes as it stands at quote
time (rounded half-up to a whole cent), then setup fee + language fee.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from util import ceil_div

SETUP_FEE_CENTS = 15000
NON_EN_LANGUAGE_FEE_CENTS = 5000

TIER_MULTIPLIER = {
    "STANDARD": Decimal("1.00"),
    "EXPRESS": Decimal("1.50"),
    "RUSH": Decimal("2.00"),
    "SAME_DAY": Decimal("2.50"),
}

TURNAROUND_TIERS = set(TIER_MULTIPLIER)


def program_minutes(duration_seconds):
    """Program length in whole minutes, rounded up."""
    return ceil_div(duration_seconds, 60)


def _round_cent(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote_price_cents(tier, duration_seconds, language, ytd_completed_minutes):
    m = program_minutes(duration_seconds)
    # Marginal brackets (NOT average-rate): first 30 min @350, next 60 @300,
    # every minute beyond 90 @250.
    duration_charge = (
        350 * min(m, 30)
        + 300 * min(max(m - 30, 0), 60)
        + 250 * max(m - 90, 0)
    )
    # Multiplier applied BEFORE the discount.
    tiered = _round_cent(Decimal(duration_charge) * TIER_MULTIPLIER[tier])
    if ytd_completed_minutes >= 10000:
        discount_pct = Decimal("0.10")
    elif ytd_completed_minutes >= 5000:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0")
    discounted = _round_cent(Decimal(tiered) * (Decimal("1") - discount_pct))
    language_fee = 0 if language == "en-US" else NON_EN_LANGUAGE_FEE_CENTS
    return SETUP_FEE_CENTS + discounted + language_fee


# --- SLA turnaround window -------------------------------------------------

BUSINESS_START_H = 9
BUSINESS_END_H = 17


def sla_hours(tier, duration_seconds):
    m = program_minutes(duration_seconds)
    if tier == "STANDARD":
        return 120 + 24 * max(0, ceil_div(m, 60) - 1)
    if tier == "EXPRESS":
        return 48 + 12 * max(0, ceil_div(m, 60) - 1)
    if tier == "RUSH":
        return 24 + 6 * ceil_div(max(0, m - 30), 30)
    # SAME_DAY
    return 8


def _add_business_hours(start, hours):
    """Consume hours only inside Mon-Fri [09:00, 17:00) UTC windows; weekends
    skipped. If start falls outside a window the clock starts at the next
    window open."""
    remaining = int(hours * 3600)
    t = start
    while True:
        if t.weekday() < 5:  # Monday..Friday
            win_open = t.replace(hour=BUSINESS_START_H, minute=0, second=0, microsecond=0)
            win_close = t.replace(hour=BUSINESS_END_H, minute=0, second=0, microsecond=0)
            if t < win_open:
                t = win_open
            if win_open <= t < win_close:
                avail = int((win_close - t).total_seconds())
                if remaining <= avail:
                    return t + timedelta(seconds=remaining)
                remaining -= avail
                t = win_close
                continue
        # Outside a window (or weekend): jump to the next day at 09:00.
        t = (t + timedelta(days=1)).replace(hour=BUSINESS_START_H, minute=0, second=0, microsecond=0)


def compute_due_at(tier, duration_seconds, confirmed_at):
    h = sla_hours(tier, duration_seconds)
    if tier in ("STANDARD", "EXPRESS"):
        return _add_business_hours(confirmed_at, h)
    # RUSH / SAME_DAY consume wall-clock hours continuously.
    return confirmed_at + timedelta(hours=h)
