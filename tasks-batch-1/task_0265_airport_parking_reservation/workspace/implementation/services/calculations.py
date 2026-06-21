"""Calculation engine (PRD §3.4, §3.6, §3.7, §3.8, §2.5).

All money is integer cents. round_half_up is applied only where a multiplier
produces a fractional cent, at the step the formula designates.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (from SCAFFOLD §1.3) ----
MINUTES_PER_DAY = 1440
MINUTES_PER_HOUR = 60

OVERSTAY_GRACE_MIN = 59
OVERSTAY_RATE_BPS = 15000
OVERSTAY_FALLBACK_HOURLY_CENTS = 500

PREPAY_MIN_LEAD_HOURS = 24

NO_SHOW_RETAIN_BPS = 5000
NO_SHOW_SUSPEND_THRESHOLD = 3
NO_SHOW_GRACE_MIN = 30
CHECKIN_EARLY_GRACE_MIN = 120
BOARDING_OPEN_LEAD_MIN = 30


def round_half_up(numerator, denominator):
    """Integer-cents round-half-up of numerator/denominator."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def _ceil_to_minute(t_start, t_end):
    """Total minutes of [t_start, t_end), partial minute rounded UP."""
    delta = t_end - t_start
    total_seconds = delta.total_seconds()
    if total_seconds <= 0:
        return 0
    return math.ceil(total_seconds / 60.0)


def compute_parking_charge(snapshot, stall_class, t_start, t_end):
    """Gross charge over [t_start, t_end) per the pinned 4-step formula.

    snapshot keys: rate_mode, hourly_cents, daily_cap_cents, valet_surcharge_cents,
    oversized_multiplier_bps, ev_surcharge_cents_per_day.
    Returns integer cents (no overstay).
    """
    rate_mode = snapshot["rate_mode"]
    hourly_cents = snapshot["hourly_cents"]
    daily_cap_cents = snapshot["daily_cap_cents"]
    valet_surcharge_cents = snapshot["valet_surcharge_cents"]
    oversized_multiplier_bps = snapshot["oversized_multiplier_bps"]
    ev_surcharge_cents_per_day = snapshot["ev_surcharge_cents_per_day"]

    # Step 1 — duration decomposition (PINNED).
    total_minutes = _ceil_to_minute(t_start, t_end)
    full_days = total_minutes // MINUTES_PER_DAY
    rem_minutes = total_minutes - full_days * MINUTES_PER_DAY
    rem_hours = math.ceil(rem_minutes / MINUTES_PER_HOUR) if rem_minutes > 0 else 0

    # Step 2 — base charge by rate_mode.
    if rate_mode == "DAILY":
        billable_days = full_days + (1 if rem_minutes > 0 else 0)
        base = billable_days * daily_cap_cents
    elif rate_mode == "HOURLY":
        base = full_days * min(24 * hourly_cents, daily_cap_cents) + min(
            rem_hours * hourly_cents, daily_cap_cents
        )
    elif rate_mode == "VALET":
        base = (
            full_days * min(24 * hourly_cents, daily_cap_cents)
            + min(rem_hours * hourly_cents, daily_cap_cents)
            + valet_surcharge_cents
        )
    else:
        base = 0

    # Step 3 — class surcharges (order PINNED: oversized multiplier, then EV add).
    if stall_class == "OVERSIZED":
        base = round_half_up(base * oversized_multiplier_bps, 10000)
    if stall_class == "EV":
        billable_days_for_ev = full_days + (1 if rem_minutes > 0 else 0)
        base = base + billable_days_for_ev * ev_surcharge_cents_per_day

    # Step 4
    return base


def compute_overstay_surcharge(snapshot, scheduled_end, actual_out):
    """Returns overstay_cents (PRD §3.6)."""
    from datetime import timedelta

    grace_end = scheduled_end + timedelta(minutes=OVERSTAY_GRACE_MIN)
    if actual_out <= grace_end:
        return 0
    overstay_minutes = _ceil_to_minute(grace_end, actual_out)
    overstay_hours = math.ceil(overstay_minutes / MINUTES_PER_HOUR)
    hourly = snapshot["hourly_cents"]
    if hourly == 0:
        hourly = OVERSTAY_FALLBACK_HOURLY_CENTS
    per_hour_penalty = round_half_up(hourly * OVERSTAY_RATE_BPS, 10000)
    return overstay_hours * per_hour_penalty


def compute_prepay_discount(gross, prepaid, lead_minutes, no_show_strikes, prepay_discount_bps):
    """Returns (provisional_quote_cents, discount_cents) per PRD §3.4."""
    eligible = (
        prepaid
        and lead_minutes >= PREPAY_MIN_LEAD_HOURS * 60
        and no_show_strikes < NO_SHOW_SUSPEND_THRESHOLD
    )
    if eligible:
        discount_cents = round_half_up(gross * prepay_discount_bps, 10000)
    else:
        discount_cents = 0
    return gross - discount_cents, discount_cents


def compute_cancellation_fee(provisional_quote_cents, hours_to_start, free_cancel_hours, late_cancel_fee_bps):
    """Returns (retained_fee_cents, refund_cents) per PRD §3.8.

    hours_to_start is the gap from current clock to scheduled_start in hours.
    """
    if hours_to_start >= free_cancel_hours:
        retained_fee_cents = 0
    else:
        retained_fee_cents = round_half_up(
            provisional_quote_cents * late_cancel_fee_bps, 10000
        )
    refund_cents = provisional_quote_cents - retained_fee_cents
    return retained_fee_cents, refund_cents


def compute_no_show_fee(provisional_quote_cents):
    """Returns (retained_fee_cents, refund_cents) per PRD §3.7."""
    retained_fee_cents = round_half_up(provisional_quote_cents * NO_SHOW_RETAIN_BPS, 10000)
    refund_cents = provisional_quote_cents - retained_fee_cents
    return retained_fee_cents, refund_cents
