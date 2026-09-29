"""Pure calculation rules (PRD Sections 2.8, 2.9, 3.5, 3.6, 3.7, 3.9).

Nothing in here touches the store; every function is a pure function of its
arguments so the rounding order pinned by the PRD is easy to audit.
"""

from decimal import Decimal, ROUND_CEILING

from core import dec, rhu, rhu2, add_years

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# calculations.replacement_value
DEPRECIATION_PER_YEAR = Decimal("0.10")
DEPRECIATION_CAP = Decimal("0.60")
RESIDUAL_FLOOR_PCT = Decimal("0.25")
BRAND_COST_BASIS_PCT = Decimal("0.90")

# calculations.repair_versus_replace
CATEGORY_REPAIR_CAP_PCT = {
    "SHELL_APPAREL": 65,
    "INSULATION": 60,
    "TENT_SHELTER": 70,
    "PACK_HARNESS": 75,
    "HARDGOODS_FRAME": 55,
}
AGE_DECAY_PCT_PER_YEAR = 5
LIFETIME_BONUS_PCT = 10
FLOOR_PCT = 30
CEILING_PCT = 90

# calculations.paid_repair_pricing
LABOR_RATE_CENTS_PER_HOUR = {"FABRIC": 8500, "ZIPPER": 9500, "FRAME": 11000, "INSULATION": 9000}
SUPPLY_FEE_PCT = Decimal("0.07")
SUPPLY_FEE_CAP_CENTS = 2500
LOYALTY_DISCOUNT_PCT = {"STANDARD": Decimal("0.00"), "PRO": Decimal("0.10")}
EXPEDITE_FEE_CENTS = 3500
TAX_PCT = Decimal("0.0825")
ESTIMATE_VALIDITY_DAYS = 7

# calculations.turnaround_commitment
CATEGORY_BASE_DAYS = {
    "SHELL_APPAREL": 10,
    "INSULATION": 14,
    "TENT_SHELTER": 12,
    "PACK_HARNESS": 9,
    "HARDGOODS_FRAME": 16,
}
WORK_TYPE_ADD_DAYS = {"FABRIC": 2, "ZIPPER": 3, "FRAME": 5, "INSULATION": 6}
PARTS_WAIT_DAYS = {"SUPPORTED": 0, "SUBSTITUTION_ONLY": 7, "NO_SUPPORT": 14}

# calculations.technician_routing_selector
WORK_TYPE_MIN_LEVEL = {"FABRIC": 1, "ZIPPER": 2, "FRAME": 2, "INSULATION": 2}

# calculations.trade_in_credit
TRADE_IN_PCT = {"A": Decimal("0.35"), "B": Decimal("0.22"), "C": Decimal("0.12")}
GOODWILL_BONUS_CENTS = 5000
TRADE_IN_CAP_CENTS = 40000
REFURB_LIST_PCT = Decimal("0.55")

# bounded cycles
MAX_INFO_REQUESTS = 2
QC_FAIL_LIMIT = 3

# enumerations
WORK_TYPES = ("FABRIC", "ZIPPER", "FRAME", "INSULATION")
CATEGORIES = tuple(CATEGORY_REPAIR_CAP_PCT.keys())
PART_KINDS = ("FABRIC_PANEL", "ZIPPER_SLIDER", "FRAME_SEGMENT", "INSULATION_FILL", "BUCKLE")
DETERMINATIONS = ("MANUFACTURING_DEFECT", "NORMAL_WEAR", "USER_DAMAGE", "INCONCLUSIVE")
DEFECT_TYPES = (
    "SEAM_FAILURE", "ZIPPER_FAILURE", "DELAMINATION", "FRAME_FRACTURE",
    "INSULATION_LOSS", "ABRASION_WEAR",
)
PROOF_TYPES = ("RECEIPT", "REGISTRATION", "RETAILER_LOOKUP", "NONE")
CONDITION_GRADES = ("A", "B", "C")
DISPOSITION_STATES = (
    "WITH_CUSTOMER", "AT_CENTER", "IN_REPAIR", "IRREPARABLE_HOLD", "RETURNED",
    "TRADED_IN", "REFURB_LISTED", "RESOLD", "RECYCLED",
)
CLAIM_TERMINAL = ("WEAR_DENIED", "CLOSED_FULFILLED", "CLOSED_REPLACED", "CLOSED_DECLINED")
ORDER_WORK_TERMINAL = ("RELEASED", "IRREPARABLE", "CLOSED_UNREPAIRED")
ITEM_TERMINAL = ("RETURNED", "RESOLD", "RECYCLED")
QUEUE_STATES = ("QUEUED", "IN_WORK", "BENCH_DONE")


# --------------------------------------------------------------------------- #
# Section 2.8 -- age and the two valuations
# --------------------------------------------------------------------------- #

def age_months(purchase_dt, now_dt):
    """Whole months elapsed, floored; a month elapses when the day-of-month is reached."""
    if purchase_dt is None:
        return 0
    months = (now_dt.year - purchase_dt.year) * 12 + (now_dt.month - purchase_dt.month)
    if now_dt.day < purchase_dt.day:
        months -= 1
    return months if months > 0 else 0


def completed_years(months):
    return months // 12


def warranty_state(model, purchase_dt, now_dt):
    if model.get("lifetime_warranty"):
        return "LIFETIME"
    expiry = add_years(purchase_dt, int(model.get("warranty_years") or 0))
    return "IN_WARRANTY" if now_dt <= expiry else "EXPIRED"


def replacement_value_depreciated(purchase_price_cents, model_msrp_cents, years):
    depreciation = DEPRECIATION_PER_YEAR * dec(years)
    if depreciation > DEPRECIATION_CAP:
        depreciation = DEPRECIATION_CAP
    residual_floor = rhu(dec(model_msrp_cents) * RESIDUAL_FLOOR_PCT)
    walked_down = rhu(dec(purchase_price_cents) * (Decimal("1") - depreciation))
    return residual_floor if residual_floor > walked_down else walked_down


def replacement_value_successor(base_msrp_cents):
    return rhu(dec(base_msrp_cents) * BRAND_COST_BASIS_PCT)


# --------------------------------------------------------------------------- #
# Section 3.5 -- repair versus replace
# --------------------------------------------------------------------------- #

def decision_threshold_pct(model, item_age_months):
    raw = CATEGORY_REPAIR_CAP_PCT[model["category"]]
    if model.get("lifetime_warranty"):
        raw += LIFETIME_BONUS_PCT
    raw -= AGE_DECAY_PCT_PER_YEAR * completed_years(item_age_months)
    capped = CEILING_PCT if raw > CEILING_PCT else raw
    return FLOOR_PCT if capped < FLOOR_PCT else capped


def repair_ratio_pct(latest_repair_cost_cents, replacement_value_successor_cents):
    if not replacement_value_successor_cents:
        return 0.0
    return rhu2(
        dec(100) * dec(latest_repair_cost_cents) / dec(replacement_value_successor_cents)
    )


def adjudicate(determination, item_warranty_state, parts_support_status, ratio_pct, threshold_pct):
    """Section 3.5 step three: branches top to bottom, first match wins.

    Returns the outcome string, or None when the live finding is INCONCLUSIVE.
    """
    if determination == "INCONCLUSIVE":
        return None
    if determination == "USER_DAMAGE":
        return "PAID_REPAIR_OFFERED"
    if determination == "NORMAL_WEAR":
        if parts_support_status == "NO_SUPPORT":
            return "WEAR_DENIED"
        return "PAID_REPAIR_OFFERED"
    # MANUFACTURING_DEFECT below
    if item_warranty_state == "EXPIRED":
        return "PAID_REPAIR_OFFERED"
    if parts_support_status == "NO_SUPPORT":
        return "WARRANTY_REPLACE"
    if dec(ratio_pct) >= dec(threshold_pct):
        return "WARRANTY_REPLACE"
    return "WARRANTY_REPAIR"


# --------------------------------------------------------------------------- #
# Section 3.7 -- paid-repair pricing
# --------------------------------------------------------------------------- #

def labor_subtotal(labor_lines):
    """Per-line round half up, taken in ascending work_type order, then summed."""
    total = 0
    for line in sorted(labor_lines, key=lambda l: l["work_type"]):
        rate = LABOR_RATE_CENTS_PER_HOUR[line["work_type"]]
        total += rhu(dec(rate) * dec(line["minutes"]) / dec(60))
    return total


def supply_fee(labor_subtotal_cents):
    fee = rhu(SUPPLY_FEE_PCT * dec(labor_subtotal_cents))
    return SUPPLY_FEE_CAP_CENTS if fee > SUPPLY_FEE_CAP_CENTS else fee


def price(labor_lines, parts_lines, loyalty_tier, variant, expedite_requested):
    labor = labor_subtotal(labor_lines)
    parts = 0
    for line in parts_lines:
        parts += int(line["units"]) * int(line["unit_price_cents"])
    supply = supply_fee(labor)
    subtotal = labor + parts + supply
    loyalty = rhu(dec(subtotal) * LOYALTY_DISCOUNT_PCT[loyalty_tier])
    expedite = EXPEDITE_FEE_CENTS if (variant == "FINAL" and expedite_requested) else 0
    tax = rhu(TAX_PCT * dec(subtotal - loyalty + expedite))
    total = subtotal - loyalty + expedite + tax
    return {
        "labor_subtotal_cents": labor,
        "parts_subtotal_cents": parts,
        "shop_supply_fee_cents": supply,
        "subtotal_cents": subtotal,
        "loyalty_discount_cents": loyalty,
        "expedite_fee_cents": expedite,
        "tax_cents": tax,
        "total_cents": total,
    }


def assessment_repair_cost(estimated_labor_lines, estimated_parts_cents):
    """The labour block only: steps 1-4, no discount, no expedite, no tax."""
    labor = labor_subtotal(estimated_labor_lines)
    return labor + int(estimated_parts_cents) + supply_fee(labor)


# --------------------------------------------------------------------------- #
# Section 3.6 -- turnaround commitment
# --------------------------------------------------------------------------- #

def tier_multiplier(queue_depth):
    if queue_depth <= 9:
        return Decimal("1.00")
    if queue_depth <= 24:
        return Decimal("1.25")
    if queue_depth <= 49:
        return Decimal("1.60")
    return Decimal("2.00")


def base_days(category, required_work_types):
    add = 0
    for work_type in required_work_types:
        candidate = WORK_TYPE_ADD_DAYS.get(work_type, 0)
        if candidate > add:
            add = candidate
    return CATEGORY_BASE_DAYS[category] + add


def promised_days(base_day_total, multiplier, parts_wait):
    scaled = (dec(base_day_total) * dec(multiplier)).to_integral_value(rounding=ROUND_CEILING)
    return int(scaled) + int(parts_wait)


# --------------------------------------------------------------------------- #
# Section 2.9 -- liability posture
# --------------------------------------------------------------------------- #

def utilization_pct(open_cents, cap_cents):
    if not cap_cents:
        return 0.0
    return rhu2(dec(100) * dec(open_cents) / dec(cap_cents))


def posture(open_cents, cap_cents):
    if open_cents > cap_cents:
        return "FROZEN"
    if open_cents * 100 > 60 * cap_cents:
        return "CONSTRAINED"
    return "OPEN"


# --------------------------------------------------------------------------- #
# Section 3.9 -- trade-in
# --------------------------------------------------------------------------- #

def trade_in_credit(depreciated_cents, grade, goodwill_applies):
    base_credit = rhu(dec(depreciated_cents) * TRADE_IN_PCT[grade])
    goodwill = GOODWILL_BONUS_CENTS if goodwill_applies else 0
    credit = base_credit + goodwill
    return TRADE_IN_CAP_CENTS if credit > TRADE_IN_CAP_CENTS else credit


def refurb_list_price(successor_cents):
    return rhu(dec(successor_cents) * REFURB_LIST_PCT)


# --------------------------------------------------------------------------- #
# Section 2.10 -- lot status
# --------------------------------------------------------------------------- #

def lot_status(available_units, low_watermark_units):
    if available_units <= 0:
        return "DEPLETED"
    if available_units <= low_watermark_units:
        return "LOW"
    return "AVAILABLE"


# --------------------------------------------------------------------------- #
# Section 3.5 -- repairability feedback
# --------------------------------------------------------------------------- #

def repairability_flag(defect_claim_count, irreparable_count):
    if defect_claim_count >= 5 and irreparable_count >= 2:
        return "REDESIGN_REQUESTED"
    if defect_claim_count >= 3:
        return "WATCH"
    return "NONE"
