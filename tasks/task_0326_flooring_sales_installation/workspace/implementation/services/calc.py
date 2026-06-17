"""Calculation rules (§1.3 / PRD §3): waste factor, estimate totals, ready
date, crew day load, warranty risk. All money uses Decimal + ROUND_HALF_UP."""
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import clock

TEAR_OUT_LABOR_CENTS_PER_SQFT = 150
SECONDS_PER_DAY = 86400

BASE_WASTE_PCT = {"HARDWOOD": 10.0, "LVP": 8.0, "TILE": 12.0, "CARPET": 5.0}
SEAM_PER_ROOM_PCT = 1.0
SEAM_CAP_PCT = 6.0
BIG_AREA_THRESHOLD_SQFT = 600
BIG_AREA_SURCHARGE_PCT = 3.0

BASE_RISK = {"HARDWOOD": 30, "LVP": 15, "TILE": 40, "CARPET": 10}
TEAR_PER_50_SQFT = 1.0
TEAR_CAP = 20.0
BACKORDER_PER_EVENT = 5.0
BACKORDER_CAP = 25.0
REMEASURE_FLAT = 10.0


def _round_half_up(value, places):
    """Round a real value to the given decimal places using ROUND_HALF_UP."""
    q = Decimal(1).scaleb(-places)  # 10**-places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round a real value to whole integer cents, half up."""
    return int(_round_half_up(value, 0))


def round_pct_1dp(value):
    """Round to 1 decimal place half up; return a float."""
    return float(_round_half_up(value, 1))


def round_sqft_2dp(value):
    """Round square footage to 2 decimal places half up; return a float."""
    return float(_round_half_up(value, 2))


def waste_factor_pct(category, measured_sqft, room_count):
    """§1.3 waste_factor — sum of category base, seam allowance, big-area surcharge.

    Result kept to 1 decimal place, round half up. Big-area threshold is strict
    (> 600 triggers; exactly 600 does not).
    """
    base = BASE_WASTE_PCT[category]
    seam = min((room_count - 1) * SEAM_PER_ROOM_PCT, SEAM_CAP_PCT)
    big = (
        BIG_AREA_SURCHARGE_PCT
        if (category in ("TILE", "HARDWOOD") and measured_sqft > BIG_AREA_THRESHOLD_SQFT)
        else 0.0
    )
    return round_pct_1dp(base + seam + big)


def provisional_estimate(product, declared_sqft):
    """§1.3 estimate_total, PROVISIONAL variant. Returns dict of computed fields."""
    billable_sqft = declared_sqft  # raw, no waste
    material_cents = round_cents(billable_sqft * product["material_cost_per_sqft_cents"])
    if product["requires_underlayment"]:
        underlayment_cents = round_cents(
            billable_sqft * product["underlayment_cost_per_sqft_cents"]
        )
    else:
        underlayment_cents = 0
    labor_cents = round_cents(declared_sqft * product["labor_rate_per_sqft_cents"])
    total_cents = material_cents + underlayment_cents + labor_cents
    return {
        "billable_sqft": billable_sqft,
        "material_cost_cents": material_cents,
        "underlayment_cost_cents": underlayment_cents,
        "labor_cost_cents": labor_cents,
        "total_cents": total_cents,
    }


def measured_estimate(product, measured_sqft, tear_out_sqft, waste_pct):
    """§1.3 estimate_total, MEASURED variant.

    Rounding order pinned: billable_sqft -> 2dp; each line -> whole cents; THEN sum.
    Labor priced off measured_sqft (not billable) + tear-out labor.
    """
    billable_sqft = round_sqft_2dp(measured_sqft * (1 + waste_pct / 100.0))
    material_cents = round_cents(billable_sqft * product["material_cost_per_sqft_cents"])
    if product["requires_underlayment"]:
        underlayment_cents = round_cents(
            billable_sqft * product["underlayment_cost_per_sqft_cents"]
        )
    else:
        underlayment_cents = 0
    install_labor_cents = round_cents(measured_sqft * product["labor_rate_per_sqft_cents"])
    tear_out_labor_cents = round_cents(tear_out_sqft * TEAR_OUT_LABOR_CENTS_PER_SQFT)
    labor_cents = install_labor_cents + tear_out_labor_cents
    total_cents = material_cents + underlayment_cents + labor_cents
    return {
        "billable_sqft": billable_sqft,
        "material_cost_cents": material_cents,
        "underlayment_cost_cents": underlayment_cents,
        "labor_cost_cents": labor_cents,
        "total_cents": total_cents,
    }


def ready_date(lead_time_days):
    """§1.3 ready_date — current clock + lead_time_days whole days, ISO 8601 UTC."""
    target = clock.now() + timedelta(seconds=lead_time_days * SECONDS_PER_DAY)
    return clock.iso(target)


def warranty_risk_score(category, tear_out_sqft, backorder_count, ever_remeasured):
    """§1.3 warranty_risk — sum additive components THEN clamp to [0,100], 1dp."""
    base = BASE_RISK[category]
    tear_component = min(math.floor(tear_out_sqft / 50.0) * TEAR_PER_50_SQFT, TEAR_CAP)
    backorder_component = min(backorder_count * BACKORDER_PER_EVENT, BACKORDER_CAP)
    remeasure_component = REMEASURE_FLAT if ever_remeasured else 0.0
    raw = base + tear_component + backorder_component + remeasure_component
    clamped = max(0.0, min(100.0, raw))
    return round_pct_1dp(clamped)
