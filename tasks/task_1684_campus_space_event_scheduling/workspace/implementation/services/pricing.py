"""Money math (PRD 2.7, 3.4, 3.6, 3.7).  All monetary values are integer cents;
every rounding is round-half-up to whole cents applied exactly where the PRD
pins it.  Decimal arithmetic only - never float."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from constants import (
    BPS_DENOMINATOR,
    CANCEL_TIER_FREE_HOURS,
    CANCEL_TIER_FULL_BPS,
    CANCEL_TIER_HALF_BPS,
    CANCEL_TIER_HALF_HOURS,
    INSURANCE_SURCHARGE_BPS,
    LATE_RETURN_FORFEIT_BPS,
    PEAK_HOUR_START,
)


def rhu_div(numerator, denominator):
    """round_half_up(numerator / denominator) to a whole integer, exactly."""
    if denominator == 0:
        return 0
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _bucket_is_peak(bucket_start):
    """A bucket is PEAK iff its starting clock hour is >= 18:00 UTC or its date
    falls on a Saturday/Sunday in UTC."""
    return bucket_start.hour >= PEAK_HOUR_START or bucket_start.weekday() >= 5


def room_charge_cents(billable_start, billable_end, pinned_rate_cents, pinned_multiplier_bps):
    """Split the billable interval into wall-clock-hour buckets aligned to UTC
    hour boundaries; every touched bucket counts as ONE full billed hour
    (partial buckets round UP).  Each bucket is rounded to cents FIRST, then
    the rounded bucket charges are summed (sum-then-round is forbidden)."""
    total = 0
    bucket = billable_start.replace(minute=0, second=0, microsecond=0)
    while bucket < billable_end:
        bucket_end = bucket + timedelta(hours=1)
        if bucket_end > billable_start:  # touched by [billable_start, billable_end)
            if _bucket_is_peak(bucket):
                total += rhu_div(pinned_rate_cents * pinned_multiplier_bps, BPS_DENOMINATOR)
            else:
                total += pinned_rate_cents
        bucket = bucket_end
    return total


def cancellation_fee_cents(base_cents, notice):
    """Tiered client-cancellation fee over the pinned provisional base.

    notice >= 72h -> 0; 24h <= notice < 72h -> 5000 bps; notice < 24h ->
    10000 bps.  Exactly 72h is free; exactly 24h is the half tier.  Rounding is
    applied once over the pinned base."""
    notice_seconds = notice.total_seconds()
    if notice_seconds >= CANCEL_TIER_FREE_HOURS * 3600:
        return 0
    if notice_seconds >= CANCEL_TIER_HALF_HOURS * 3600:
        bps = CANCEL_TIER_HALF_BPS
    else:
        bps = CANCEL_TIER_FULL_BPS
    return rhu_div(base_cents * bps, BPS_DENOMINATOR)


def insurance_surcharge_cents(room_plus_service_cents, org_type):
    """EXTERNAL only: round_half_up(2% * (room + service)); 0 otherwise."""
    if org_type != "EXTERNAL":
        return 0
    return rhu_div(room_plus_service_cents * INSURANCE_SURCHARGE_BPS, BPS_DENOMINATOR)


def late_return_forfeit_cents(deposit_cents):
    """Late return forfeits round_half_up(deposit * 0.5)."""
    return rhu_div(deposit_cents * LATE_RETURN_FORFEIT_BPS, BPS_DENOMINATOR)
