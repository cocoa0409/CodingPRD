"""Calculation rules (scaffold section 1.3). Integer cents only; Decimal for
half-up rounding at exactly the pinned step (PRD 2.6)."""

import calendar
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

TIER_MEDIUM_FLOOR_CENTS = 100000
TIER_HIGH_FLOOR_CENTS = 500000


def _round_half_up_cents(numer, denom):
    """round_half_up(numer / denom) to whole cents, for non-negative integers."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def disclosure_tier(fmv_cents):
    """LOW < 100000; 100000..500000 MEDIUM; > 500000 HIGH."""
    if fmv_cents < TIER_MEDIUM_FLOOR_CENTS:
        return "LOW"
    if fmv_cents <= TIER_HIGH_FLOOR_CENTS:
        return "MEDIUM"
    return "HIGH"


def minimum_bid_cents(bundle_fmv_cents, event):
    """Pinned order: bps-round (half-up) -> floor -> ceil-to-grid (PRD 3.4)."""
    raw = _round_half_up_cents(bundle_fmv_cents * event["min_bid_pct_bps"], 10000)
    floored = max(raw, event["min_bid_floor_cents"])
    inc = event["min_bid_increment_cents"]
    return -(-floored // inc) * inc


def min_next_bid_cents(bundle, event, has_active_bid):
    """First tier with up_to_cents null or STRICTLY greater than the high bid."""
    if not has_active_bid:
        return bundle["min_bid_cents"]
    high = bundle["current_high_bid_cents"]
    tiers = event["bid_increment_tiers"]
    for tier in tiers:
        if tier["up_to_cents"] is None or high < tier["up_to_cents"]:
            return high + tier["increment_cents"]
    return high + tiers[-1]["increment_cents"]


def split_portions(winning_bid_cents, pinned_bundle_fmv_cents):
    """AGGREGATE variant (authoritative). Contribution exists only when the
    winning bid is STRICTLY greater than the pinned FMV."""
    revenue = min(winning_bid_cents, pinned_bundle_fmv_cents)
    contribution = max(0, winning_bid_cents - pinned_bundle_fmv_cents)
    return revenue, contribution


def prorata_contribution(winning_bid_cents, pinned_bundle_fmv_cents, member_fmv_cents_list):
    """PRORATA variant: per-line round_half_up allocations, no remainder
    reconciliation; total = sum(max(0, alloc_i - fmv_i))."""
    total = 0
    for fmv_i in member_fmv_cents_list:
        alloc = _round_half_up_cents(winning_bid_cents * fmv_i, pinned_bundle_fmv_cents)
        total += max(0, alloc - fmv_i)
    return total


def add_months(dt, months):
    """Calendar-month addition: same day-of-month (clamped), time-of-day preserved."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)
