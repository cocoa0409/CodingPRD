"""Money / proration / intensity calculations (PRD Section 3, 2.7).

All money is integer cents. round_half_up is the global tie-breaker (PRD 2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

CYCLE_DAYS = 30
PER_WASH_VALUE_CENTS = 400
MAX_ATTEMPTS = 3
ACUTE_CAP = 8
CHRONIC_CAP = Decimal("12.00")


def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half away from zero."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fleet_discount_pct(account_type, active_vehicle_count):
    """Volume-tier discount (PRD 2.10). INDIVIDUAL is always 0.

    Returned as a Decimal rate (e.g. Decimal('0.15')).
    """
    if account_type != "FLEET":
        return Decimal("0")
    if active_vehicle_count >= 10:
        return Decimal("0.15")
    if active_vehicle_count >= 5:
        return Decimal("0.10")
    if active_vehicle_count >= 2:
        return Decimal("0.05")
    return Decimal("0")


def cycle_discount_cents(subtotal_cents, discount_pct):
    """Fleet discount applied to a cycle subtotal (PRD 3.4 / calc invoice_cycle_total).

    round_half_up applied to discount_cents only.
    """
    return round_half_up_cents(Decimal(subtotal_cents) * discount_pct)


def elapsed_days(cycle_anchor_utc, current_utc):
    """Whole days from cycle anchor to now, partial day discarded (floor) (PRD 3.5)."""
    delta = current_utc - cycle_anchor_utc
    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        total_seconds = 0
    return int(total_seconds // 86400)


def remaining_days(cycle_anchor_utc, current_utc):
    return CYCLE_DAYS - elapsed_days(cycle_anchor_utc, current_utc)


def proration_lines(old_monthly_fee, new_monthly_fee, added_addon_fees, rem_days):
    """Plan-change proration (PRD 3.5 / calc proration_on_plan_change).

    Each line is rounded half-up independently, THEN summed (pinned order).
    Returns (plan_delta_line, addon_lines_sum, total).
    """
    plan_delta_line = round_half_up_cents(
        Decimal(new_monthly_fee - old_monthly_fee) * Decimal(rem_days) / Decimal(CYCLE_DAYS)
    )
    addon_lines_sum = 0
    for fee in added_addon_fees:
        addon_lines_sum += round_half_up_cents(
            Decimal(fee) * Decimal(rem_days) / Decimal(CYCLE_DAYS)
        )
    return plan_delta_line, addon_lines_sum, plan_delta_line + addon_lines_sum


def freeze_refund_cents(current_cycle_paid_cents, rem_days):
    """Forward-looking pro-rated freeze refund (PRD 3.8)."""
    refund = round_half_up_cents(
        Decimal(current_cycle_paid_cents) * Decimal(rem_days) / Decimal(CYCLE_DAYS)
    )
    return max(0, refund)


def cancellation_refund_unlimited(current_cycle_paid_cents, rem_days):
    """UNLIMITED cancellation refund = unused value (PRD 3.10), floored at 0."""
    refund = round_half_up_cents(
        Decimal(current_cycle_paid_cents) * Decimal(rem_days) / Decimal(CYCLE_DAYS)
    )
    return max(0, refund)


def cancellation_refund_single_wash(current_cycle_paid_cents, credits_consumed_this_cycle):
    """SINGLE_WASH cancellation refund = consumed value (PRD 3.10), floored at 0."""
    refund = current_cycle_paid_cents - (credits_consumed_this_cycle * PER_WASH_VALUE_CENTS)
    return max(0, refund)


def chronic_intensity(lifetime_admitted, vehicle_created_at, current_utc):
    """Lifetime admitted washes / active months, 2dp round_half_up (PRD 3.7)."""
    delta_days = (current_utc - vehicle_created_at).total_seconds() / 86400.0
    # active months = max(1, ceil(days / 30))
    import math
    spans = math.ceil(delta_days / 30.0) if delta_days > 0 else 0
    active_months = max(1, spans)
    value = Decimal(lifetime_admitted) / Decimal(active_months)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_abuse(acute, chronic):
    return acute >= ACUTE_CAP or Decimal(str(chronic)) >= CHRONIC_CAP
