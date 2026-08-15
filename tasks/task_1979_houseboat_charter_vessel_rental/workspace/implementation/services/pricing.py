"""Pricing calculations: rental_quote and deposit_requirement (scaffold §1.3)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db
import errors

MAX_BOOKING_NIGHTS = 21

BASE_DEPOSIT = {
    "COMPACT_36": 150000,
    "STANDARD_44": 200000,
    "LUXE_56": 250000,
}
TIER_MED_MIN = 20
TIER_HIGH_MIN = 50

SIZE_CLASSES = ("COMPACT_36", "STANDARD_44", "LUXE_56")
SEASONS = ("PEAK", "SHOULDER", "OFF_PEAK")


def nights_of(start_date, end_date):
    """Half-open stay: every date d with start_date <= d < end_date."""
    count = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(count)]


def rate_covering(size_class, night):
    """The SeasonRate of this size_class whose closed interval covers night."""
    for r in db.all_of("season_rates"):
        if r["size_class"] != size_class:
            continue
        if r["start_date"] <= night <= r["end_date"]:
            return r
    return None


def rental_quote(vessel, start_date, end_date):
    """Night-by-night pricing with per-window weekly discount.

    Raises ERR_RATE_NOT_CONFIGURED when any night lacks a covering rate.
    Weekly runs never span a season boundary: nights are counted per window
    and only complete runs of 7 within that window are discounted.
    """
    nights = nights_of(start_date, end_date)
    subtotal = 0
    nights_per_rate = {}
    for d in nights:
        r = rate_covering(vessel["size_class"], d)
        if r is None:
            errors.err(
                errors.ERR_RATE_NOT_CONFIGURED,
                f"No season rate configured for size class {vessel['size_class']} on {d.isoformat()}",
            )
        subtotal += r["nightly_rate_cents"]
        nights_per_rate[r["id"]] = nights_per_rate.get(r["id"], 0) + 1
    discount = 0
    for rate_id, n_r in nights_per_rate.items():
        r = db.get("season_rates", rate_id)
        runs = n_r // 7
        if runs == 0 or r["weekly_discount_pct"] == 0:
            continue
        raw = (
            Decimal(runs * 7 * r["nightly_rate_cents"] * r["weekly_discount_pct"])
            / Decimal(100)
        )
        discount += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return subtotal - discount


def deposit_multiplier_for(rolling_score):
    if rolling_score < TIER_MED_MIN:
        return 1.0
    if rolling_score < TIER_HIGH_MIN:
        return 1.5
    return 2.0


def deposit_requirement(size_class, rolling_score):
    """BASE_DEPOSIT[size_class] x multiplier; exact integer cents."""
    mult = deposit_multiplier_for(rolling_score)
    product = Fraction(BASE_DEPOSIT[size_class]) * Fraction(str(mult))
    return int(product)


# Orientation item set pinned by size class at confirm time (PRD §3.5).
ORIENTATION_BASE_ITEMS = ["SAFETY_BRIEF", "DOCKING", "ANCHORING", "GENERATOR_OPS"]
ORIENTATION_LUXE_ITEMS = ["THRUSTER_OPS", "SEWAGE_PUMPOUT"]


def orientation_item_set(size_class):
    items = list(ORIENTATION_BASE_ITEMS)
    if size_class == "LUXE_56":
        items.extend(ORIENTATION_LUXE_ITEMS)
    return items
