"""Pricing and commission calculations."""

import math
from decimal import Decimal

from money import commission_rate, round_half_up_to_int, to_decimal


def scheduled_minutes_of(start_dt, end_dt):
    """Compute scheduled minutes — seconds between end and start divided by 60.0, then ceil'd."""
    delta_seconds = (end_dt - start_dt).total_seconds()
    if delta_seconds <= 0:
        return 0
    return math.ceil(delta_seconds / 60.0)


def _discount_multiplier(scheduled_minutes, is_trial):
    if is_trial:
        return Decimal("1")
    if scheduled_minutes >= 180:
        return Decimal("0.90")
    if scheduled_minutes >= 120:
        return Decimal("0.95")
    return Decimal("1")


def compute_gross_cents(tutor, start_dt, end_dt, is_trial):
    """pricing_gross calculation. Returns (gross_cents, scheduled_minutes)."""
    minutes = scheduled_minutes_of(start_dt, end_dt)
    base_rate_per_min = to_decimal(
        tutor["trial_rate_cents"] if is_trial else tutor["hourly_rate_cents"]
    ) / Decimal("60")
    raw = base_rate_per_min * Decimal(minutes)
    raw = raw * _discount_multiplier(minutes, is_trial)
    return round_half_up_to_int(raw), minutes


def compute_actual_gross_cents(tutor, scheduled_minutes, actual_minutes, is_trial):
    """Recompute gross at completion using actual (clamped) minutes."""
    actual = max(0, min(actual_minutes, scheduled_minutes))
    base_rate_per_min = to_decimal(
        tutor["trial_rate_cents"] if is_trial else tutor["hourly_rate_cents"]
    ) / Decimal("60")
    raw = base_rate_per_min * Decimal(actual)
    raw = raw * _discount_multiplier(scheduled_minutes, is_trial)
    return round_half_up_to_int(raw)


def compute_commission_cents(base_cents, lifetime_completed):
    rate = commission_rate(lifetime_completed)
    raw = to_decimal(base_cents) * rate
    return round_half_up_to_int(raw)


def compute_cancellation_fee_cents(charged_amount_cents, hours_to_start, by_tutor_or_system):
    """cancellation_fee calculation."""
    if by_tutor_or_system:
        return 0
    if hours_to_start >= 24:
        return 0
    if hours_to_start >= 2:
        raw = to_decimal(charged_amount_cents) * Decimal("0.25")
        return round_half_up_to_int(raw)
    raw = to_decimal(charged_amount_cents) * Decimal("0.50")
    return round_half_up_to_int(raw)
