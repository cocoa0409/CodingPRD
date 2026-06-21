"""Calculation rules from scaffold §1.3 / PRD §3.5, §3.7."""
import math
from decimal import Decimal, ROUND_HALF_UP

import constants as C
import clock


def oversize_fee_cents(size_tier, longest_dim_cm, weight_g):
    """Pinned once at receipt against the assigned locker's size_tier."""
    tier_max_dim = C.TIER_MAX_DIM[size_tier]
    tier_max_wt = C.TIER_MAX_WEIGHT[size_tier]
    dim_over_units = max(0, math.ceil((longest_dim_cm - tier_max_dim) / C.DIM_BUCKET_CM))
    wt_over_units = max(0, math.ceil((weight_g - tier_max_wt) / C.WT_BUCKET_G))
    raw_fee = dim_over_units * C.OVERSIZE_DIM_RATE_CENTS + wt_over_units * C.OVERSIZE_WT_RATE_CENTS
    return min(raw_fee, C.OVERSIZE_FEE_CAP_CENTS)


def overstay_fee_cents(notified_at_instant, reference_instant, size_tier, time_zone):
    """Calendar-day overstay measured in the facility time_zone."""
    if notified_at_instant is None or reference_instant is None:
        return 0
    stored_days = clock.calendar_days_between(notified_at_instant, reference_instant, time_zone)
    if stored_days < 0:
        stored_days = 0
    overstay_days = max(0, stored_days - C.GRACE_DAYS)
    daily_rate = C.OVERSTAY_DAILY_RATE_CENTS[size_tier]
    return overstay_days * daily_rate


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def prorated_refund_chronological(monthly_fee_cents, term_months, term_start_instant,
                                  close_instant, time_zone):
    term_days = term_months * C.DAYS_PER_MONTH
    paid_cents = monthly_fee_cents * term_months
    used_days = clock.calendar_days_between(term_start_instant, close_instant, time_zone)
    used_days = max(0, min(used_days, term_days))
    # division first, single round-half-up at the very end
    refund = Decimal(paid_cents) * Decimal(term_days - used_days) / Decimal(term_days)
    return _round_half_up(refund)


def prorated_refund_forward_looking(monthly_fee_cents, term_months, term_start_instant,
                                    close_instant, time_zone):
    term_days = term_months * C.DAYS_PER_MONTH
    used_days = clock.calendar_days_between(term_start_instant, close_instant, time_zone)
    used_days = max(0, min(used_days, term_days))
    months_used = math.ceil(used_days / C.DAYS_PER_MONTH)
    months_remaining = max(0, term_months - months_used)
    return monthly_fee_cents * months_remaining


def forwarding_fee_cents(kind):
    return C.FORWARD_FEE_CENTS if kind == "FORWARD" else C.SCAN_FEE_CENTS
