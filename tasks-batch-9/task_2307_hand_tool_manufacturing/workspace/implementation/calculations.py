"""All calculation rules (§1.3 / PRD §3). Decimal arithmetic, round half up."""

from decimal import Decimal, ROUND_HALF_UP

D = Decimal

# --------------------------------------------------------------------------- #
# enums
# --------------------------------------------------------------------------- #
TOOL_FAMILIES = ["WRENCH", "SOCKET", "PLIER"]
CHANNELS = ["BRANDED", "PRIVATE_LABEL", "PROFESSIONAL"]
ALLOY_GRADES = ["CR_V", "CR_MO", "S2"]
WARRANTY_TIERS = ["LIFETIME", "LIMITED_5Y", "NONE"]
PROCESS_STATUSES = ["FORGED", "HEAT_TREATED", "MACHINED", "PLATED", "ASSEMBLED"]
CERT_STATUSES = ["DRAFT", "IN_TEST", "CERTIFIED", "REJECTED"]
DISPOSITIONS = ["IN_PROCESS", "RELEASED", "QUARANTINED"]
FURNACE_STATUSES = ["AVAILABLE", "MAINTENANCE"]
CAMPAIGN_STATUSES = ["SCHEDULED", "COMPLETED", "RELEASED"]
TEST_TYPES = ["HARDNESS", "PROOF_TORQUE", "DIMENSIONAL", "SALT_SPRAY", "MECHANISM_CYCLE"]
TEST_RUN_STATUSES = ["SCHEDULED", "PASSED", "FAILED", "VOID"]
PACK_TYPES = ["RETAIL_DISPLAY", "SECURITY", "MULTIPACK"]
PACK_STATUSES = ["DRAFT", "APPROVED", "WITHDRAWN"]
CLAIMANT_TYPES = ["CONSUMER", "PRO_ACCOUNT"]
CLAIMANT_STATUSES = ["ACTIVE", "BLOCKED"]
CLAIM_REASONS = ["BREAKAGE", "MECHANISM_FAILURE", "CORROSION"]
CLAIM_STATUSES = [
    "SUBMITTED", "FRAUD_HOLD", "APPROVED", "FULFILLED", "DENIED", "DENIED_FRAUD", "REVOKED",
]
EVIDENCE_GRADES = ["WEAK", "MODERATE", "STRONG"]
REPORT_STATUSES = ["OPEN", "CONFIRMED", "DISMISSED"]
POSTURES = ["OPEN", "RESTRICTED", "SUSPENDED"]

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
BASE_TORQUE_PER_MM = {"WRENCH": D("4.2"), "SOCKET": D("6.5"), "PLIER": D("2.8")}
ALLOY_FACTOR = {"CR_V": D("1.00"), "CR_MO": D("1.15"), "S2": D("1.30")}
CHANNEL_FACTOR = {"BRANDED": D("1.10"), "PRIVATE_LABEL": D("1.00"), "PROFESSIONAL": D("1.25")}
SIZE_TIER_SMALL_MAX = 10
SIZE_TIER_MID_MAX = 19
SIZE_TIER_ADD = {"small": D("0.0"), "mid": D("1.5"), "large": D("3.0")}
FLOOR_NM = D("12.0")
CEIL_NM = D("900.0")

HARDNESS_MIN_HRC = {"CR_V": D("47.0"), "CR_MO": D("50.0"), "S2": D("55.0")}
CHANNEL_HARDNESS_MARGIN = {"BRANDED": D("1.0"), "PRIVATE_LABEL": D("0.0"), "PROFESSIONAL": D("2.5")}
SALT_SPRAY_MIN_HOURS = {"BRANDED": D("96"), "PRIVATE_LABEL": D("48"), "PROFESSIONAL": D("168")}
MECHANISM_MIN_CYCLES = D("5000")
DIM_TOLERANCE_MM = D("0.15")

MANDATORY_TESTS = {
    "WRENCH": ["HARDNESS", "PROOF_TORQUE", "DIMENSIONAL", "SALT_SPRAY"],
    "SOCKET": ["HARDNESS", "PROOF_TORQUE", "DIMENSIONAL", "SALT_SPRAY"],
    "PLIER": ["HARDNESS", "DIMENSIONAL", "SALT_SPRAY", "MECHANISM_CYCLE"],
}

# process stage required before a test type may be scheduled (PRD §3.3)
TEST_STAGE_REQUIREMENT = {
    "HARDNESS": None,
    "DIMENSIONAL": "MACHINED",
    "PROOF_TORQUE": "MACHINED",
    "SALT_SPRAY": "PLATED",
    "MECHANISM_CYCLE": "ASSEMBLED",
}
# test types that require heat treatment to have happened (temporal gate)
HEAT_TREAT_DEPENDENT_TESTS = {"DIMENSIONAL", "PROOF_TORQUE", "SALT_SPRAY", "MECHANISM_CYCLE"}

RAMP_BUFFER_MINUTES = 45
MIN_SOAK_MINUTES = 60
REWORK_LIMIT = 2
LINEAGE_MAX_DEPTH = 3

EVIDENCE_POINTS = {"WEAK": D("5"), "MODERATE": D("15"), "STRONG": D("30")}
UNIT_SCALE_LOW_MAX = 50
UNIT_SCALE_MID_MAX = 500
UNIT_SCALE_POINTS = {"low": D("0"), "mid": D("8"), "high": D("20")}
CHANNEL_EXPOSURE = {"BRANDED": D("1.0"), "PRIVATE_LABEL": D("0.6"), "PROFESSIONAL": D("0.8")}
POSTURE_RESTRICT_AT = 40
POSTURE_SUSPEND_AT = 85

CLAIM_WINDOW_DAYS = 365
BASE_POINTS_PER_CLAIM = 9
PRO_ACCOUNT_ALLOWANCE = 2
SERIAL_REPEAT_PENALTY = 18
COUNTERFEIT_LINK_PENALTY = 25

CHANNEL_RESERVE_PCT = {"BRANDED": D("0.62"), "PRIVATE_LABEL": D("0.45"), "PROFESSIONAL": D("0.78")}
WARRANTY_TIER_FACTOR = {"LIFETIME": D("1.00"), "LIMITED_5Y": D("0.70"), "NONE": D("0.00")}

PACK_TYPE_DISCOUNT = {"RETAIL_DISPLAY": D("1.00"), "SECURITY": D("1.00"), "MULTIPACK": D("0.88")}
SURCHARGE_BREAK_LOW = 5000
SURCHARGE_BREAK_MID = 20000
SURCHARGE_FLAT_LOW = 350
SURCHARGE_FLAT_MID = 700
SURCHARGE_HIGH_PCT = D("0.04")


# --------------------------------------------------------------------------- #
# rounding helpers
# --------------------------------------------------------------------------- #
def rhu(value, places=0):
    """Round half up to `places` decimals. Returns Decimal."""
    q = D(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec(value):
    """Coerce an int/float/Decimal reading into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return D(value)
    return D(repr(float(value)))


def mean(values):
    total = sum(values, D(0))
    return total / D(len(values))


def num(value):
    """JSON-friendly number for a Decimal (or None)."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# proof_torque_requirement
# --------------------------------------------------------------------------- #
def size_tier_add(nominal_size_mm):
    if nominal_size_mm <= SIZE_TIER_SMALL_MAX:
        return SIZE_TIER_ADD["small"]
    if nominal_size_mm <= SIZE_TIER_MID_MAX:
        return SIZE_TIER_ADD["mid"]
    return SIZE_TIER_ADD["large"]


def proof_torque_requirement(tool_family, nominal_size_mm, alloy_grade, channel):
    size = D(nominal_size_mm)
    raw = BASE_TORQUE_PER_MM[tool_family] * size * ALLOY_FACTOR[alloy_grade]
    adjusted = raw * CHANNEL_FACTOR[channel] + size_tier_add(nominal_size_mm) * size
    clamped = min(CEIL_NM, max(FLOOR_NM, adjusted))
    return rhu(clamped, 1)


# --------------------------------------------------------------------------- #
# lot_hardness_index (dual variant)
# --------------------------------------------------------------------------- #
def lot_hardness_index(qualifying_runs):
    """qualifying_runs: PASSED HARDNESS runs on the lot, created_at ASC.

    Returns (sample, pooled) as Decimals, or (None, None) when the set is empty.
    """
    if not qualifying_runs:
        return None, None
    run_means = []
    pooled = []
    for run in qualifying_runs:
        readings = [dec(r) for r in run["readings"]]
        run_means.append(rhu(mean(readings), 1))
        pooled.extend(readings)
    sample = rhu(mean(run_means), 2)
    pooled_index = rhu(mean(pooled), 2)
    return sample, pooled_index


# --------------------------------------------------------------------------- #
# test_run_outcome
# --------------------------------------------------------------------------- #
def requirement_for(test_type, lot, sku):
    if test_type == "HARDNESS":
        return HARDNESS_MIN_HRC[sku["alloy_grade"]]
    if test_type == "PROOF_TORQUE":
        return D(lot["proof_torque_required_nm"])
    if test_type == "SALT_SPRAY":
        return SALT_SPRAY_MIN_HOURS[sku["channel"]]
    if test_type == "MECHANISM_CYCLE":
        return MECHANISM_MIN_CYCLES
    return DIM_TOLERANCE_MM  # DIMENSIONAL


def test_run_outcome(test_type, raw_readings, requirement):
    readings = [dec(r) for r in raw_readings]
    mean_reading = rhu(mean(readings), 1)
    if test_type == "HARDNESS":
        governing = mean_reading
        at_least = True
    elif test_type == "DIMENSIONAL":
        governing = max(abs(r) for r in readings)
        at_least = False
    else:  # PROOF_TORQUE, SALT_SPRAY, MECHANISM_CYCLE
        governing = min(readings)
        at_least = True

    requirement = D(requirement)
    if at_least:
        passed = governing >= requirement
        margin = (governing - requirement) / requirement * D(100)
    else:
        passed = governing <= requirement
        margin = (requirement - governing) / requirement * D(100)
    return {
        "mean_reading": mean_reading,
        "governing_statistic": governing,
        "requirement_value": requirement,
        "result_margin_pct": rhu(margin, 2),
        "status": "PASSED" if passed else "FAILED",
    }


# --------------------------------------------------------------------------- #
# brand_risk_rollup
# --------------------------------------------------------------------------- #
def unit_scale_points(unit_estimate):
    if unit_estimate <= UNIT_SCALE_LOW_MAX:
        return UNIT_SCALE_POINTS["low"]
    if unit_estimate <= UNIT_SCALE_MID_MAX:
        return UNIT_SCALE_POINTS["mid"]
    return UNIT_SCALE_POINTS["high"]


def report_risk_points(evidence_grade, unit_estimate, sku_channel):
    base = EVIDENCE_POINTS[evidence_grade] + unit_scale_points(unit_estimate)
    return rhu_int(base * CHANNEL_EXPOSURE[sku_channel])


def derive_posture(brand_risk_score):
    if brand_risk_score >= POSTURE_SUSPEND_AT:
        return "SUSPENDED"
    if brand_risk_score >= POSTURE_RESTRICT_AT:
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------- #
# claimant_fraud_score
# --------------------------------------------------------------------------- #
def fraud_score(claim_set, claimant_type, restricted_links=0):
    allowance = PRO_ACCOUNT_ALLOWANCE if claimant_type == "PRO_ACCOUNT" else 0
    groups = {}
    for claim in claim_set:
        groups[claim["serial_code"]] = groups.get(claim["serial_code"], 0) + 1
    dup_serials = sum(count - 1 for count in groups.values())
    score = ((len(claim_set) - allowance) * BASE_POINTS_PER_CLAIM
             + dup_serials * SERIAL_REPEAT_PENALTY
             + restricted_links * COUNTERFEIT_LINK_PENALTY)
    return min(100, max(0, score))


# --------------------------------------------------------------------------- #
# claim_reserve_charge
# --------------------------------------------------------------------------- #
def line_reserve_cents(component_list_price_cents, quantity, sku):
    product = (D(component_list_price_cents) * D(quantity)
               * CHANNEL_RESERVE_PCT[sku["channel"]]
               * WARRANTY_TIER_FACTOR[sku["warranty_tier"]])
    return rhu_int(product)


# --------------------------------------------------------------------------- #
# pack_pricing
# --------------------------------------------------------------------------- #
def member_line_extended_cents(list_price_cents, quantity, pack_type):
    return rhu_int(D(list_price_cents) * D(quantity) * PACK_TYPE_DISCOUNT[pack_type])


def security_surcharge_cents(pack_type, member_subtotal_cents):
    if pack_type != "SECURITY":
        return 0
    if member_subtotal_cents <= SURCHARGE_BREAK_LOW:
        return SURCHARGE_FLAT_LOW
    if member_subtotal_cents <= SURCHARGE_BREAK_MID:
        return SURCHARGE_FLAT_MID
    return rhu_int(D(member_subtotal_cents) * SURCHARGE_HIGH_PCT)


# --------------------------------------------------------------------------- #
# sku_lineage_depth
# --------------------------------------------------------------------------- #
def lineage_walk(skus, candidate_id, self_id=None):
    """Walk the supersedes chain from the candidate ancestor.

    Returns the hop count. Raises LineageError(ERR_SKU_LINEAGE_CYCLE) when the
    walk revisits a SKU (including the SKU being registered / amended itself).
    The depth limit is enforced by the caller, after the family check, because
    the validation ladder orders cycle (910) < family (911) < depth (912).
    """
    if candidate_id is None:
        return 0
    seen = set()
    if self_id:
        seen.add(self_id)
    cursor = candidate_id
    hops = 0
    while cursor is not None:
        if cursor in seen:
            raise LineageError("ERR_SKU_LINEAGE_CYCLE")
        seen.add(cursor)
        hops += 1
        row = skus.get(cursor)
        if row is None:
            break
        cursor = row.get("supersedes_sku_id")
    return hops


class LineageError(Exception):
    def __init__(self, error_id):
        super().__init__(error_id)
        self.error_id = error_id
