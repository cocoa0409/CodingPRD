"""Calculation rules (PRD §2.9, §3.7-§3.9; SCAFFOLD §1.3).

All money is integer cents. Division uses round-half-up (PRD §2.9).
"""
import calendar
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> integer cents.

    Uses Decimal so a fractional half-cent rounds up to the next cent
    (PRD §2.9). Never uses float.
    """
    if denominator == 0:
        return 0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def whole_days(start_dt, end_dt):
    """Whole days in the half-open span [start, end). Floor of the day count."""
    delta = end_dt - start_dt
    return int(delta.total_seconds() // 86400)


def calendar_month_days(dt):
    """Number of days in the full calendar month containing dt."""
    return calendar.monthrange(dt.year, dt.month)[1]


def dues_proration_provisional(base_cents, period_start, period_end):
    """PROVISIONAL daily-calendar variant (PRD §3.8 / SCAFFOLD dues_proration).

    covered_days = whole days in [period_start, period_end)
    billing_days = days in the calendar month containing period_start
    gross = round_half_up(base * covered_days / billing_days)
    """
    covered = whole_days(period_start, period_end)
    billing = calendar_month_days(period_start)
    return round_half_up(base_cents * covered, billing)


def pt_package_price(list_price_cents, discount_pct):
    """price_paid = round_half_up(list_price * (1 - discount_pct)) (PRD §3.9).

    Apply the discount to the WHOLE list price, round once. discount_pct is a
    fraction 0.0..0.5. Use Decimal end-to-end to avoid float error.
    """
    factor = (Decimal(1) - Decimal(str(discount_pct)))
    raw = Decimal(list_price_cents) * factor
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def delinquency_status(elapsed_days, delinquent_after, suspended_after):
    """Threshold ladder (PRD §3.4 / SCAFFOLD delinquency_day_count).

    Inclusive boundaries: >= 30 -> SUSPENDED, >= 15 -> DELINQUENT, else PAST_DUE.
    """
    if elapsed_days >= suspended_after:
        return "SUSPENDED"
    if elapsed_days >= delinquent_after:
        return "DELINQUENT"
    return "PAST_DUE"
