"""Calculation rules (SCAFFOLD §1.3 / PRD §3.6, §3.9).

All money is integer cents. Fractional cents round half-up. Hours round to
2dp half-up.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- constants (from scaffold §1.3) ----------------------------------------
OT_DAILY_THRESHOLD_HOURS = Decimal("8.0")
OT_MULTIPLIER = Decimal("1.5")
HOLIDAY_MULTIPLIER = Decimal("2.0")
MULTI_CHILD_SURCHARGE_PCT_PER_EXTRA = Decimal("0.10")
LAST_MINUTE_WINDOW_HOURS = 24
LAST_MINUTE_SURCHARGE_PCT = Decimal("0.15")

FICA_EMPLOYEE_RATE = Decimal("0.0765")
PLATFORM_FEE_PCT = Decimal("0.10")
FICA_ANNUAL_WAGE_THRESHOLD_CENTS = 270000

TRAVEL_BUFFER_MINUTES = 30


def round_half_up_cents(value):
    """Round a Decimal to whole integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_hours_2dp(value):
    """Round a Decimal hours value to 2 decimal places, half-up; return Decimal."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def hours_between(start_dt, end_dt):
    """Span in hours as a Decimal rounded to 2dp half-up."""
    seconds = Decimal((end_dt - start_dt).total_seconds())
    hours = seconds / Decimal(3600)
    return round_hours_2dp(hours)


def _session_gross(hours, agreed_rate_cents, num_children, is_holiday, is_last_minute):
    """Shared pay engine for both estimate and final pay.

    hours: Decimal (already rounded to 2dp)
    Returns integer cents (round half-up at the end).
    """
    hours = Decimal(hours)
    child_mult = Decimal(1) + MULTI_CHILD_SURCHARGE_PCT_PER_EXTRA * (Decimal(num_children) - 1)
    eff_rate = Decimal(agreed_rate_cents) * child_mult

    if is_holiday:
        base = hours * eff_rate * HOLIDAY_MULTIPLIER
    else:
        reg_hours = min(hours, OT_DAILY_THRESHOLD_HOURS)
        ot_hours = max(Decimal(0), hours - OT_DAILY_THRESHOLD_HOURS)
        base = reg_hours * eff_rate + ot_hours * eff_rate * OT_MULTIPLIER

    gross = base
    if is_last_minute:
        gross = gross * (Decimal(1) + LAST_MINUTE_SURCHARGE_PCT)

    return round_half_up_cents(gross)


def compute_estimated_session_pay(scheduled_start, scheduled_end, agreed_rate_cents,
                                  num_children, is_holiday, is_last_minute):
    """Forward estimate from the first session's SCHEDULED window (§3.6)."""
    hours = hours_between(scheduled_start, scheduled_end)
    return _session_gross(hours, agreed_rate_cents, num_children, is_holiday, is_last_minute)


def compute_final_session_pay(clock_in_at, clock_out_at, agreed_rate_cents,
                              num_children, is_holiday, is_last_minute):
    """Final pay from ACTUAL clocked hours (§3.6). Returns (actual_hours, gross_cents)."""
    actual_hours = hours_between(clock_in_at, clock_out_at)
    gross = _session_gross(actual_hours, agreed_rate_cents, num_children,
                           is_holiday, is_last_minute)
    return actual_hours, gross


def compute_payout_withholding(session_gross_list):
    """PINNED order: round FICA per-session then sum (§3.9).

    session_gross_list: list of integer gross_pay_cents (in sweep order).
    Returns (gross, fica, fee, net).
    """
    gross = sum(session_gross_list)
    fica = sum(
        round_half_up_cents(Decimal(g) * FICA_EMPLOYEE_RATE)
        for g in session_gross_list
    )
    fee = round_half_up_cents(Decimal(gross) * PLATFORM_FEE_PCT)
    net = gross - fica - fee
    return gross, fica, fee, net
