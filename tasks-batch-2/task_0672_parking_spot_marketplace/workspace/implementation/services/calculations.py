"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All money is integer cents. Where a basis-point multiplier yields a fractional cent
the result is rounded half-up. Each function pins the rounding step exactly as the
scaffold specifies (multiply-then-round, per-line fee rounding, etc.).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

NEUTRAL_BPS = 10000
WEEKEND_BPS = 11000
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
OVERSTAY_RATE_BPS = 15000
BPS_DENOM = 10000

KIND_WEIGHT = {"OVERSTAY": 1, "UNAUTHORIZED_GATE": 2, "NO_SHOW": 3}

ESCALATION_STEP_BPS = 2500
ESCALATION_CAP_STEPS = 3

WATCH_THRESHOLD = 5
SUSPENDED_THRESHOLD = 10

# Refund tier thresholds (seconds)
SEVEN_DAYS_S = 604800
ONE_DAY_S = 86400


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def booking_quote_amount(rate_kind, start_at, end_at, spot, matched_event):
    """§1.3 booking_quote_amount — frozen into Booking.quoted_amount_cents.

    Multiply-then-round at the single 'raw' step.
    """
    duration_seconds = (end_at - start_at).total_seconds()

    if rate_kind == "HOURLY":
        units = math.ceil(duration_seconds / SECONDS_PER_HOUR)
        base = units * spot["base_hourly_cents"]
    elif rate_kind == "DAILY":
        units = math.ceil(duration_seconds / SECONDS_PER_DAY)
        base = units * spot["base_daily_cents"]
    else:  # MONTHLY: flat 30-day block, units fixed at 1
        base = spot["monthly_flat_cents"]

    surge_bps = matched_event["surge_multiplier_bps"] if matched_event else NEUTRAL_BPS

    # Weekend uplift applies only to HOURLY/DAILY whose start_at is Sat/Sun (UTC).
    if rate_kind != "MONTHLY" and start_at.weekday() in (5, 6):  # 5=Sat, 6=Sun
        weekend_bps = WEEKEND_BPS
    else:
        weekend_bps = NEUTRAL_BPS

    # raw = base * surge_bps/10000 * weekend_bps/10000 ; round ONCE here.
    raw = Decimal(base) * Decimal(surge_bps) / Decimal(BPS_DENOM) \
        * Decimal(weekend_bps) / Decimal(BPS_DENOM)
    quoted = max(round_half_up(raw), spot["base_hourly_cents"])
    return quoted


def final_settlement_amount(booking, spot, actual_checkout_at):
    """§1.3 final_settlement_amount — written to Booking.final_amount_cents.

    Base portion is the frozen quote. Overstay is billed at 1.5x base hourly,
    rounded half-up on the overstay term only, then added to integer base portion.
    """
    end_at = booking["_end_at_dt"]
    grace_seconds = spot["overstay_grace_minutes"] * 60
    base_portion = booking["quoted_amount_cents"]

    overstay_seconds = (actual_checkout_at - end_at).total_seconds() - grace_seconds
    if overstay_seconds <= 0:
        overstay_charge = 0
    else:
        overstay_hours = math.ceil(overstay_seconds / SECONDS_PER_HOUR)
        overstay_charge = round_half_up(
            Decimal(overstay_hours) * Decimal(spot["base_hourly_cents"])
            * Decimal(OVERSTAY_RATE_BPS) / Decimal(BPS_DENOM)
        )

    return base_portion + overstay_charge


def host_net_earning(gross_cents, platform_fee_bps):
    """§1.3 host_payout_amount — per-booking fee rounded half-up, THEN subtracted.

    Returns the positive net earning for an EARNING entry.
    """
    fee_cents = round_half_up(
        Decimal(gross_cents) * Decimal(platform_fee_bps) / Decimal(BPS_DENOM)
    )
    return gross_cents - fee_cents


def provisional_points_for(violation_kind, base_points):
    """Provisional contribution of an OPEN record: base_points * weight, no escalation."""
    return base_points * KIND_WEIGHT[violation_kind]


def confirmed_violation_points(violation_kind, base_points, prior_confirmed):
    """§1.3 confirmed_violation_points — assessed points on confirm.

    escalation_bps = 10000 + min(prior_confirmed, 3) * 2500 ; round half-up to points.
    """
    escalation_bps = NEUTRAL_BPS + min(prior_confirmed, ESCALATION_CAP_STEPS) * ESCALATION_STEP_BPS
    assessed = round_half_up(
        Decimal(base_points) * Decimal(KIND_WEIGHT[violation_kind])
        * Decimal(escalation_bps) / Decimal(BPS_DENOM)
    )
    return assessed


def driver_standing_tier(violation_points):
    """§1.3 driver_standing_tier — >= boundaries on CONFIRMED points."""
    if violation_points >= SUSPENDED_THRESHOLD:
        return "SUSPENDED"
    if violation_points >= WATCH_THRESHOLD:
        return "WATCH"
    return "GOOD"


def refund_amount(quoted_amount_cents, lead_seconds):
    """§1.3 refund_amount — tiered refund of frozen quote by lead time before start_at."""
    if lead_seconds >= SEVEN_DAYS_S:
        refund_bps = 10000
    elif lead_seconds >= ONE_DAY_S:
        refund_bps = 7500
    elif lead_seconds >= 0:
        refund_bps = 5000
    else:
        refund_bps = 0
    return round_half_up(
        Decimal(quoted_amount_cents) * Decimal(refund_bps) / Decimal(BPS_DENOM)
    )
