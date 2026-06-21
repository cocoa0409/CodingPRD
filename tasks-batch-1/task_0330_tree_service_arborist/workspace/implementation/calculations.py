"""All monetary / scoring calculations (SCAFFOLD section 1.3, PRD section 3).

Money is integer cents throughout, rounded half-up. Decimal is used so that
rate * fractional-quantity and percentage surcharges stay exact before rounding.
"""
import math
from decimal import Decimal

from helpers import round_half_up

# ---- tree_hazard_score constants ----
DBH_TIER_LARGE_IN = 36
DBH_TIER_MED_IN = 18
LEAN_STEP_DEG = 5
LEAN_CAP = 30
DECAY_POINTS = 20
TIER_SEVERE_MIN = 70
TIER_MODERATE_MIN = 40

# ---- line_item_cost constants ----
REMOVAL_SMALL_CENTS = 45000
REMOVAL_MED_CENTS = 95000
REMOVAL_LARGE_CENTS = 180000
STUMP_CENTS_PER_INCH = 1200
HAUL_OFF_CENTS_PER_TON = 8500
UTILITY_LINE_ITEM_CENTS = 60000

# ---- estimate_total constants ----
HAZARD_PCT_SEVERE = Decimal("0.20")
HAZARD_PCT_MODERATE = Decimal("0.10")
UTILITY_PER_TREE_CENTS = 25000
EMERGENCY_MULTIPLIER = Decimal("1.5")

# ---- booking_billed_cost constants ----
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = Decimal("1.5")


def tree_hazard_score(dbh_inches, lean_degrees, has_visible_decay):
    """Return (hazard_score:int, hazard_tier:str)."""
    if dbh_inches >= DBH_TIER_LARGE_IN:
        dbh_component = 50
    elif dbh_inches >= DBH_TIER_MED_IN:
        dbh_component = 30
    else:
        dbh_component = 10

    lean_component = min(LEAN_CAP, math.floor(lean_degrees / LEAN_STEP_DEG) * 10)
    decay_component = DECAY_POINTS if has_visible_decay else 0

    score = dbh_component + lean_component + decay_component

    if score >= TIER_SEVERE_MIN:
        tier = "SEVERE"
    elif score >= TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return score, tier


def hazard_level_from_tiers(tiers):
    """Max tier over a set of per-tree tiers; LOW when empty."""
    order = {"LOW": 0, "MODERATE": 1, "SEVERE": 2}
    best = "LOW"
    for t in tiers:
        if order[t] > order[best]:
            best = t
    return best


def _hazard_pct(hazard_level):
    if hazard_level == "SEVERE":
        return HAZARD_PCT_SEVERE
    if hazard_level == "MODERATE":
        return HAZARD_PCT_MODERATE
    return Decimal("0")


def line_item_unit_cost(service_type, tree_dbh_inches=None):
    """Resolve per-unit cost in integer cents from service_type (+ dbh tier)."""
    if service_type == "REMOVAL":
        if tree_dbh_inches >= DBH_TIER_LARGE_IN:
            return REMOVAL_LARGE_CENTS
        elif tree_dbh_inches >= DBH_TIER_MED_IN:
            return REMOVAL_MED_CENTS
        else:
            return REMOVAL_SMALL_CENTS
    if service_type == "STUMP_GRINDING":
        return STUMP_CENTS_PER_INCH
    if service_type == "HAUL_OFF":
        return HAUL_OFF_CENTS_PER_TON
    if service_type == "UTILITY_CLEARANCE":
        return UTILITY_LINE_ITEM_CENTS
    raise ValueError(f"unknown service_type {service_type!r}")


def line_item_extended_cost(unit_cost_cents, quantity):
    """Per-line rounding: round(unit_cost_cents * quantity) half-up, once per line."""
    raw = Decimal(unit_cost_cents) * Decimal(str(quantity))
    return round_half_up(raw)


def estimate_total(*, line_items_subtotal_cents, hazard_level, pricing_mode,
                   is_emergency, heritage_surcharge_pct,
                   utility_tree_count, has_heritage_removal):
    """Compute all surcharge fields and total per the pinned order.

    Returns dict with hazard_surcharge_cents, utility_surcharge_cents,
    heritage_surcharge_cents, total_cents, emergency_multiplier_applied.
    """
    subtotal = Decimal(line_items_subtotal_cents)

    hazard_pct = _hazard_pct(hazard_level)
    hazard_surcharge = round_half_up(subtotal * hazard_pct)

    utility_surcharge = UTILITY_PER_TREE_CENTS * utility_tree_count

    if pricing_mode == "PER_JOB" and has_heritage_removal:
        heritage_surcharge = round_half_up(subtotal * Decimal(str(heritage_surcharge_pct)))
    else:
        heritage_surcharge = 0

    pre_emergency = (line_items_subtotal_cents + hazard_surcharge
                     + utility_surcharge + heritage_surcharge)

    if is_emergency:
        total = round_half_up(Decimal(pre_emergency) * EMERGENCY_MULTIPLIER)
        emergency_applied = True
    else:
        total = pre_emergency
        emergency_applied = False

    return {
        "hazard_surcharge_cents": hazard_surcharge,
        "utility_surcharge_cents": utility_surcharge,
        "heritage_surcharge_cents": heritage_surcharge,
        "total_cents": total,
        "emergency_multiplier_applied": emergency_applied,
    }


def booking_billed_cost(rate_cents_per_hour, actual_hours):
    """Regular hours at rate, overtime (>8h) at 1.5x; single final rounding."""
    rate = Decimal(rate_cents_per_hour)
    hours = Decimal(str(actual_hours))
    threshold = Decimal(OT_THRESHOLD_HOURS)

    reg_hours = min(hours, threshold)
    ot_hours = max(Decimal(0), hours - threshold)

    amount = rate * reg_hours + rate * OT_MULTIPLIER * ot_hours
    return round_half_up(amount)


def disposal_fee(debris_tons, fee_cents_per_ton):
    raw = Decimal(str(debris_tons)) * Decimal(fee_cents_per_ton)
    return round_half_up(raw)


def final_invoice(*, pricing_mode, accepted_estimate_total, hazard_level,
                  labor_cost_accrued_cents, disposal_cost_accrued_cents):
    """PER_JOB: frozen accepted estimate total. HOURLY: metered + hazard surcharge."""
    if pricing_mode == "PER_JOB":
        return accepted_estimate_total or 0
    accruals = labor_cost_accrued_cents + disposal_cost_accrued_cents
    hazard_pct = _hazard_pct(hazard_level)
    hazard_surcharge = round_half_up(Decimal(accruals) * hazard_pct)
    return accruals + hazard_surcharge
