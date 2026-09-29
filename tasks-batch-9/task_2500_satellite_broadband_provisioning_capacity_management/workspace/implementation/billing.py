"""Outage credits and cycle charges (PRD 3.8, 3.9).

Both money calculations pin an evaluation order, and in both cases summing
first and rounding once is explicitly not the rule.
"""

from datetime import datetime, timedelta, timezone

from constants import (
    CAUSE_MULTIPLIER,
    CREDIT_CAP_FRACTION,
    DISCOUNT_BAND_1_CENTS,
    DISCOUNT_BAND_1_PCT,
    DISCOUNT_BAND_2_CENTS,
    DISCOUNT_BAND_2_PCT,
    MINUTES_PER_BILLING_MONTH,
    SEVERITY_FACTOR,
)
from numeric import cents, dec, floor_minutes


def credit_multiplier(event):
    return CAUSE_MULTIPLIER[event["cause"]] * SEVERITY_FACTOR[event["severity"]]


def credit_cap_cents(plan):
    return cents(dec(plan["monthly_fee_cents"]) * CREDIT_CAP_FRACTION)


def provisional_credit_cents(event, plan):
    """One rounding over the whole impairment span."""
    multiplier = credit_multiplier(event)
    minutes = dec(event["outage_minutes"] or 0)
    raw = dec(plan["monthly_fee_cents"]) * (minutes / MINUTES_PER_BILLING_MONTH) * multiplier
    return min(cents(raw), credit_cap_cents(plan))


def _utc_day_start(moment):
    return datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)


def day_segments(start, end):
    """Split the half-open span into half-open UTC calendar-day segments."""
    cursor = start
    while cursor < end:
        boundary = _utc_day_start(cursor) + timedelta(days=1)
        segment_end = boundary if boundary < end else end
        yield cursor, segment_end
        cursor = segment_end


def final_credit_cents(event, plan):
    """One rounding per UTC calendar day, then summed."""
    multiplier = credit_multiplier(event)
    monthly = dec(plan["monthly_fee_cents"])
    total = 0
    for segment_start, segment_end in day_segments(event["started_at"], event["ended_at"]):
        day_minutes = floor_minutes((segment_end - segment_start).total_seconds())
        total += cents(monthly * (dec(day_minutes) / MINUTES_PER_BILLING_MONTH) * multiplier)
    return min(total, credit_cap_cents(plan))


def discount_rate(gross_total_cents):
    """The band is keyed on the gross total, never on the monthly fee alone."""
    if gross_total_cents >= DISCOUNT_BAND_2_CENTS:
        return DISCOUNT_BAND_2_PCT
    if gross_total_cents >= DISCOUNT_BAND_1_CENTS:
        return DISCOUNT_BAND_1_PCT
    return dec(0)


def cycle_charge_cents(plan, overage_volume_gb):
    """Overage fee, then gross total, then band, then a single final rounding."""
    overage_fee = cents(dec(overage_volume_gb) * dec(plan["overage_rate_cents_per_gb"]))
    gross_total = int(plan["monthly_fee_cents"]) + overage_fee
    rate = discount_rate(gross_total)
    return cents(dec(gross_total) * (dec(1) - rate))
