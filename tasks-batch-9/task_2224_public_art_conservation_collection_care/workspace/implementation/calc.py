"""All calculations (PRD 2.10, 3.2, 3.4, 3.9, 3.10, 3.11).

Money is always integer cents computed through Decimal with ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- condition index -------------------------------------------------------
MATERIAL_WEIGHTS = {
    "BRONZE": {"surface": "0.30", "structural": "0.25", "coating": "0.20", "mount": "0.15", "graffiti": "0.10"},
    "PAINTED_STEEL": {"surface": "0.20", "structural": "0.20", "coating": "0.35", "mount": "0.15", "graffiti": "0.10"},
    "STONE": {"surface": "0.25", "structural": "0.35", "coating": "0.05", "mount": "0.20", "graffiti": "0.15"},
    "MURAL_COATING": {"surface": "0.35", "structural": "0.10", "coating": "0.30", "mount": "0.05", "graffiti": "0.20"},
}
EXPOSURE_PENALTY = {"COASTAL": "6.0", "URBAN": "3.0", "PARK": "1.5", "INTERIOR": "0.0"}
TREATMENT_TRIGGER_INDEX = Decimal("55.0")
MIN_ASSESSMENT_PHOTOS = 3
MAX_REVISION_ROUNDS = 2

# --- treatment priority ----------------------------------------------------
SIGNIFICANCE_FACTOR = {"LANDMARK": "1.5", "SIGNIFICANT": "1.2", "STANDARD": "1.0"}
EXPOSURE_FACTOR = {"COASTAL": "1.3", "URBAN": "1.25", "PARK": "1.1", "INTERIOR": "1.0"}
DEFERRAL_PER_DAY = Decimal("0.004")
DEFERRAL_CAP = Decimal("1.60")

# --- proposal estimate -----------------------------------------------------
COMPLEXITY_FACTOR = {
    "STABILIZATION": "1.00", "SURFACE": "1.15", "COATING": "1.25",
    "STRUCTURAL": "1.40", "GRAFFITI": "1.10",
}
OVERHEAD_PCT = Decimal("0.115")
CONTINGENCY_PCT = Decimal("0.075")
MOBILIZATION_FLAT_CENTS = 45000

# --- funding pool ----------------------------------------------------------
TIER1_FLOOR_CENTS = 5000000
TIER2_FLOOR_CENTS = 20000000
TIER1_SUPPLEMENTAL_BPS = 75
TIER2_SUPPLEMENTAL_BPS = 125
ADMIN_FEE_PCT = Decimal("0.0225")

# --- maintenance SLA -------------------------------------------------------
GRAFFITI_SLA_HOURS = {"MURAL_COATING": 48, "PAINTED_STEEL": 72, "BRONZE": 120, "STONE": 120}

# --- insurance claim -------------------------------------------------------
ANNUAL_RETENTION = Decimal("0.98")
MAX_DEPRECIATION_YEARS = 25
POLICY_LIMIT_CENTS = 25000000
DEDUCTIBLE_CENTS = 250000

# --- deaccession ballot ----------------------------------------------------
QUORUM_MIN_VOTES = 5
APPROVE_RATIO_MIN = Decimal("0.60")

# --- conservator scheduling ------------------------------------------------
CONSERVATOR_BUFFER_HOURS = 48


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def condition_index(assessment, artwork, site):
    """PRD 3.2: weighted defect, then exposure penalty, 1 dp half-up, floored at 0."""
    weights = MATERIAL_WEIGHTS[artwork["material_class"]]
    scores = {
        "surface": assessment["surface_score"],
        "structural": assessment["structural_score"],
        "coating": assessment["coating_score"],
        "mount": assessment["mount_score"],
        "graffiti": assessment["graffiti_score"],
    }
    raw_defect = Decimal(0)
    for axis, score in scores.items():
        raw_defect += D(weights[axis]) * D(score)
    severity = Decimal("1.0") if max(scores.values()) == 4 else Decimal("0.5")
    penalty = D(EXPOSURE_PENALTY[site["exposure_class"]]) * severity
    value = rhu(Decimal(100) - Decimal(25) * raw_defect - penalty, 1)
    if value < 0:
        value = Decimal("0.0")
    return float(value)


def recommendation_band(index):
    value = D(index)
    if value >= Decimal("75.0"):
        return "NONE"
    if value >= Decimal("55.0"):
        return "ROUTINE"
    if value >= Decimal("30.0"):
        return "PRIORITY"
    return "URGENT"


def treatment_priority_score(source_index, artwork, site, days_deferred):
    """PRD 3.9: deficit * significance * exposure * deferral, 2 dp half-up once."""
    deficit = Decimal(100) - D(source_index)
    sig = D(SIGNIFICANCE_FACTOR[artwork["significance_tier"]])
    expo = D(EXPOSURE_FACTOR[site["exposure_class"]])
    days = max(0, int(days_deferred))
    deferral = Decimal(1) + DEFERRAL_PER_DAY * Decimal(days)
    if deferral > DEFERRAL_CAP:
        deferral = DEFERRAL_CAP
    return float(rhu(deficit * sig * expo * deferral, 2))


def line_labor_cents(labor_hours, hourly_rate_cents, complexity_class):
    return int(rhu(D(labor_hours) * D(hourly_rate_cents) * D(COMPLEXITY_FACTOR[complexity_class]), 0))


def estimate_breakdown(line_items):
    """PRD 3.4: round per line then sum; contingency includes overhead."""
    subtotal = 0
    for line in line_items:
        subtotal += int(line["line_total_cents"])
    overhead = int(rhu(D(subtotal) * OVERHEAD_PCT, 0))
    contingency = int(rhu((D(subtotal) + D(overhead)) * CONTINGENCY_PCT, 0))
    mobilization = MOBILIZATION_FLAT_CENTS if len(line_items) > 0 else 0
    total = subtotal + overhead + contingency + mobilization
    return {
        "subtotal_cents": subtotal,
        "overhead_cents": overhead,
        "contingency_cents": contingency,
        "mobilization_cents": mobilization,
        "estimate_total_cents": total,
    }


def pool_draw(pool):
    """PRD 3.10: returns (draw_authorized_cents, admin_fee_cents)."""
    if pool["pool_type"] == "PERCENT_FOR_ART":
        authorized_before_fee = Decimal(int(pool.get("set_aside_cents") or 0))
        admin_fee = Decimal(0)
    else:
        principal = Decimal(int(pool.get("principal_cents") or 0))
        rate_bps = Decimal(int(pool.get("draw_rate_bps") or 0))
        gross = rhu(principal * rate_bps / Decimal(10000), 0)
        if gross < TIER1_FLOOR_CENTS:
            tier_bps = 0
        elif gross < TIER2_FLOOR_CENTS:
            tier_bps = TIER1_SUPPLEMENTAL_BPS
        else:
            tier_bps = TIER2_SUPPLEMENTAL_BPS
        supplemental = rhu(principal * Decimal(tier_bps) / Decimal(10000), 0)
        authorized_before_fee = gross + supplemental
        admin_fee = rhu(authorized_before_fee * ADMIN_FEE_PCT, 0)
    return int(authorized_before_fee - admin_fee), int(admin_fee)


def acv_claim_gross(insured_value_cents, elapsed_days, damage_extent_pct):
    age_years = elapsed_days // 365
    if age_years < 0:
        age_years = 0
    if age_years > MAX_DEPRECIATION_YEARS:
        age_years = MAX_DEPRECIATION_YEARS
    depreciated = rhu(D(insured_value_cents) * (ANNUAL_RETENTION ** age_years), 0)
    return int(rhu(depreciated * D(damage_extent_pct), 0))


def settlement_from_gross(claimed_gross_cents):
    capped = min(int(claimed_gross_cents), POLICY_LIMIT_CENTS)
    return max(0, capped - DEDUCTIBLE_CENTS)


def decision_ratio(approve_count, deny_count):
    denominator = approve_count + deny_count
    if denominator == 0:
        return Decimal(0)
    return D(approve_count) / D(denominator)
