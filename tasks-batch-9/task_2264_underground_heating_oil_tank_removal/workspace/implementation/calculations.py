"""Pure calculation rules — SCAFFOLD §1.3 / PRD §2.9, §3.1, §3.5-§3.9.

Money is integer cents everywhere; every rounding is half-up and happens exactly
where the PRD pins it.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- decommission_method_recommendation ------------------------------------
DEPTH_FREE_INCHES = Decimal("24")
DEPTH_POINTS_PER_INCH = Decimal("0.5")
DEPTH_FACTOR_MAX = Decimal("40.0")
FOUNDATION_CONCERN_INCHES = Decimal("60")
PROXIMITY_POINTS_PER_INCH = Decimal("0.75")
PROXIMITY_FACTOR_MAX = Decimal("30.0")
UNDER_STRUCTURE_POINTS = Decimal("35.0")
ABANDONMENT_SCORE_THRESHOLD = Decimal("55.00")

# --- contamination_classification ------------------------------------------
TPH_ACTION_MG_KG = Decimal("500.0")
TPH_GROSS_MG_KG = Decimal("5000.0")
BENZENE_ACTION_MG_KG = Decimal("0.5")
BENZENE_GROSS_MG_KG = Decimal("5.0")

# --- remediation_soil_volume ------------------------------------------------
GRID_CELL_SQFT = Decimal("100.0")
CUBIC_FEET_PER_CUBIC_YARD = Decimal("27.0")
SOIL_DENSITY_TONS_PER_CY = Decimal("1.35")

# --- remediation_cost -------------------------------------------------------
BASE_MOBILIZATION_CENTS = 185000
DISPOSAL_MULTIPLIER = {
    "NON_HAZARDOUS": Decimal("1.0"),
    "HAZARDOUS": Decimal("1.85"),
}

# --- trust_fund_eligible_amount --------------------------------------------
STATE_DEDUCTIBLE_CENTS = {"NJ": 50000, "NY": 100000, "CT": 25000}
TIER_1_MAX_CENTS = 5000000
TIER_2_MAX_CENTS = 12000000
CAP_TIER_1_CENTS = 4000000
CAP_TIER_2_CENTS = 9000000
CAP_TIER_3_CENTS = 12500000
ADMIN_FEE_RATE = Decimal("0.035")
MAX_INFO_REQUESTS = 2

# --- windows ----------------------------------------------------------------
DISCLOSURE_RESPONSE_WINDOW_HOURS = 72
FIRE_MARSHAL_NOTICE_LEAD_HOURS = 48
PERMIT_VALIDITY_DAYS = 180

SECONDS_PER_HOUR = Decimal("3600.0")

# enum vocabularies -----------------------------------------------------------
STATE_CODES = ("NJ", "NY", "CT")
SURVEY_METHODS = ("GPR", "MAGNETOMETER", "PROBE_ROD")
TANK_MATERIALS = ("STEEL", "FIBERGLASS")
DISCLOSURE_KINDS = ("SWEEP_FINDINGS", "CONTAMINATION_FINDINGS")
RESPONSE_CHANNELS = ("EMAIL", "PORTAL", "WET_SIGNATURE")
PERMIT_TYPES = ("MUNICIPAL_DECOMMISSION", "FIRE_MARSHAL_NOTIFICATION")
CERT_LEVELS = ("TANK_TECH_I", "TANK_TECH_II", "LSP_SUPERVISED")
METHODS = ("REMOVAL", "ABANDONMENT_IN_PLACE")
SAMPLE_POINTS = (
    "TANK_BOTTOM", "NORTH_SIDEWALL", "SOUTH_SIDEWALL", "STOCKPILE", "CONFIRMATION_FLOOR",
)
DISPOSAL_CLASSES = ("NON_HAZARDOUS", "HAZARDOUS")
CLAIM_VARIANTS = ("PRELIMINARY_ESTIMATE", "FINAL_SETTLEMENT")
NOTIFICATION_KINDS = ("FIRST_PARTY", "THIRD_PARTY_LIABILITY")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def round_half_up(value, places=2):
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def round_half_up_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# decommission_method_recommendation
# ---------------------------------------------------------------------------

def method_recommendation(capacity_gallons, depth_inches, distance_inches,
                         under_structure, material):
    depth_factor = min(
        DEPTH_FACTOR_MAX,
        max(Decimal("0.0"), (dec(depth_inches) - DEPTH_FREE_INCHES) * DEPTH_POINTS_PER_INCH),
    )
    proximity_factor = min(
        PROXIMITY_FACTOR_MAX,
        max(Decimal("0.0"),
            (FOUNDATION_CONCERN_INCHES - dec(distance_inches)) * PROXIMITY_POINTS_PER_INCH),
    )
    structure_factor = UNDER_STRUCTURE_POINTS if under_structure else Decimal("0.0")
    capacity = dec(capacity_gallons)
    if capacity >= Decimal("1000"):
        capacity_factor = Decimal("15.0")
    elif capacity >= Decimal("550"):
        capacity_factor = Decimal("8.0")
    else:
        capacity_factor = Decimal("0.0")
    material_factor = Decimal("10.0") if material == "STEEL" else Decimal("0.0")

    raw = depth_factor + proximity_factor + structure_factor + capacity_factor + material_factor
    # clamp BEFORE rounding — pinned order (PRD §2.9)
    score = round_half_up(min(Decimal("100.0"), raw), 2)
    method = "ABANDONMENT_IN_PLACE" if score >= ABANDONMENT_SCORE_THRESHOLD else "REMOVAL"
    return score, method


# ---------------------------------------------------------------------------
# contamination_classification
# ---------------------------------------------------------------------------

def classify(resulted_samples):
    """Returns (max_tph, max_benzene, contamination_class)."""
    if not resulted_samples:
        return None, None, "UNCLASSIFIED"
    max_tph = max(dec(s["tph_mg_kg"]) for s in resulted_samples)
    max_benzene = max(dec(s["benzene_mg_kg"]) for s in resulted_samples)
    if max_tph > TPH_GROSS_MG_KG or max_benzene > BENZENE_GROSS_MG_KG:
        klass = "GROSS"
    elif max_tph > TPH_ACTION_MG_KG or max_benzene > BENZENE_ACTION_MG_KG:
        klass = "ELEVATED"
    else:
        klass = "CLEAN"
    return max_tph, max_benzene, klass


# ---------------------------------------------------------------------------
# remediation_soil_volume
# ---------------------------------------------------------------------------

def provisional_grid_volume(impacted_samples):
    if not impacted_samples:
        return Decimal("0.00")
    grid_area_sqft = Decimal(len(impacted_samples)) * GRID_CELL_SQFT
    max_depth_ft = max(dec(s["depth_inches"]) for s in impacted_samples) / Decimal("12.0")
    return round_half_up(grid_area_sqft * max_depth_ft / CUBIC_FEET_PER_CUBIC_YARD, 2)


def final_surveyed_volume(hauled_tons):
    if hauled_tons is None:
        return None
    return round_half_up(dec(hauled_tons) / SOIL_DENSITY_TONS_PER_CY, 2)


# ---------------------------------------------------------------------------
# remediation_cost
# ---------------------------------------------------------------------------

def line_amount_cents(additional_cubic_yards, unit_rate_cents, disposal_class):
    product = (dec(additional_cubic_yards) * dec(unit_rate_cents)
               * DISPOSAL_MULTIPLIER[disposal_class])
    return round_half_up_cents(product)


# ---------------------------------------------------------------------------
# trust_fund_eligible_amount
# ---------------------------------------------------------------------------

def eligibility(state_code, claimed_costs_cents, variant, reimbursed_amount_cents=0):
    gross_cents = int(claimed_costs_cents)
    deductible_cents = STATE_DEDUCTIBLE_CENTS[state_code]
    if gross_cents <= TIER_1_MAX_CENTS:
        cap_cents = CAP_TIER_1_CENTS
    elif gross_cents <= TIER_2_MAX_CENTS:
        cap_cents = CAP_TIER_2_CENTS
    else:
        cap_cents = CAP_TIER_3_CENTS
    capped_cents = min(gross_cents, cap_cents)
    admin_fee_cents = round_half_up_cents(Decimal(capped_cents) * ADMIN_FEE_RATE)
    if variant == "PRELIMINARY_ESTIMATE":
        net_cents = max(0, capped_cents - deductible_cents) - admin_fee_cents
    else:  # FINAL_SETTLEMENT
        net_cents = max(0, min(gross_cents - deductible_cents, cap_cents)) - admin_fee_cents
    eligible_amount_cents = max(0, net_cents)
    unreimbursed_balance_cents = eligible_amount_cents - int(reimbursed_amount_cents)
    return {
        "deductible_cents": deductible_cents,
        "cap_cents": cap_cents,
        "admin_fee_cents": admin_fee_cents,
        "eligible_amount_cents": eligible_amount_cents,
        "unreimbursed_balance_cents": unreimbursed_balance_cents,
    }


# ---------------------------------------------------------------------------
# laboratory_timing
# ---------------------------------------------------------------------------

def elapsed_hours(start, end):
    delta = Decimal(str((end - start).total_seconds())) / SECONDS_PER_HOUR
    return round_half_up(delta, 2)
