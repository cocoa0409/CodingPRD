"""Domain constants for the HERS Rating & Code Compliance API.

Every value here is transcribed from the PRD:
  - §2.5 the logical clock's initial instant
  - §2.7 the code-edition / climate-zone reference tables
  - §3.1 the HERS index routine
  - §3.3 the travel buffer and duct-limit switch
  - §3.4 the compliance waterfall's tolerances and envelope ratios
  - §3.5 the sample-set size bounds
  - §3.6 the quality-assurance sampling rates
  - §3.9 the incentive tiers, per-measure rates, caps and issuance ceilings
"""

from decimal import ROUND_HALF_UP, Decimal

# --- §2.1 roles -------------------------------------------------------------
ROLE_ADMIN = "RatingProviderAdmin"
ROLE_RATER = "CertifiedRater"
ROLE_INSPECTOR = "FieldInspector"
ROLE_QA = "QADesignee"
ROLE_BUILDER_REP = "BuilderRep"

ALL_ROLES = [ROLE_ADMIN, ROLE_RATER, ROLE_INSPECTOR, ROLE_QA, ROLE_BUILDER_REP]

# --- §2.3 pagination --------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- §2.5 logical clock -----------------------------------------------------
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

# --- §2.7 reference tables --------------------------------------------------
CODE_EDITIONS = ["IECC_2015", "IECC_2021"]
CLIMATE_ZONES = ["CZ2", "CZ3", "CZ4", "CZ5", "CZ6"]

ENVELOPE_LOAD_FACTOR = {
    "CZ2": Decimal("0.90"),
    "CZ3": Decimal("0.95"),
    "CZ4": Decimal("1.00"),
    "CZ5": Decimal("1.10"),
    "CZ6": Decimal("1.20"),
}

ACH50_MAX = {
    "IECC_2015": {
        "CZ2": Decimal("5.0"),
        "CZ3": Decimal("3.0"),
        "CZ4": Decimal("3.0"),
        "CZ5": Decimal("3.0"),
        "CZ6": Decimal("3.0"),
    },
    "IECC_2021": {
        "CZ2": Decimal("5.0"),
        "CZ3": Decimal("5.0"),
        "CZ4": Decimal("3.0"),
        "CZ5": Decimal("3.0"),
        "CZ6": Decimal("3.0"),
    },
}

ERI_TARGET = {
    "IECC_2015": {"CZ2": 65, "CZ3": 65, "CZ4": 65, "CZ5": 69, "CZ6": 69},
    "IECC_2021": {"CZ2": 52, "CZ3": 53, "CZ4": 55, "CZ5": 55, "CZ6": 54},
}

PV_INDEX_CAP = {"IECC_2015": Decimal("100.0"), "IECC_2021": Decimal("5.0")}

DUCT_LIMIT_FINAL = Decimal("4.0")
DUCT_LIMIT_ROUGH_IN_WITH_AIR_HANDLER = Decimal("4.0")
DUCT_LIMIT_ROUGH_IN_WITHOUT_AIR_HANDLER = Decimal("3.0")

# --- §3.1 HERS index routine ------------------------------------------------
BASE_LOAD_ACH_COEFFICIENT = Decimal("0.60")
BASE_LOAD_ACH_DIVISOR = Decimal("1000")
BASE_LOAD_DUCT_COEFFICIENT = Decimal("0.90")
BASE_LOAD_DUCT_DIVISOR = Decimal("100")
EQUIP_MULT_INTERCEPT = Decimal("1.35")
EQUIP_MULT_SLOPE = Decimal("0.05")
EQUIP_MULT_FLOOR = Decimal("0.62")
EQUIP_MULT_CEILING = Decimal("1.05")
REFERENCE_LOAD_AREA_COEFFICIENT = Decimal("0.30")
REFERENCE_LOAD_BEDROOM_COEFFICIENT = Decimal("40.0")
PV_CREDIT_POINTS_PER_KW = Decimal("4.0")

# --- §3.3 inspector scheduling ---------------------------------------------
TRAVEL_BUFFER_MINUTES = 45

# --- §3.4 compliance waterfall ---------------------------------------------
PERFORMANCE_INDEX_TOLERANCE = 5
PRESCRIPTIVE_UA_RATIO = Decimal("0.12")
PERFORMANCE_UA_RATIO = Decimal("0.14")

# --- §3.5 sampling protocol -------------------------------------------------
SAMPLE_SET_MIN_MEMBERS_FOR_SELECTION = 2
SAMPLE_SET_MAX_MEMBERS = 7

# --- §3.6 quality-assurance quota ------------------------------------------
QA_RATE_STANDARD = Decimal("0.10")
QA_RATE_PROBATION = Decimal("1.00")

# --- §3.9 documentation packages -------------------------------------------
TAX_CREDIT_TIER_1_MAX_INDEX = 45
TAX_CREDIT_TIER_1_CENTS = 250000
TAX_CREDIT_TIER_2_MAX_INDEX = 55
TAX_CREDIT_TIER_2_CENTS = 100000
TAX_CREDIT_ZERO_CENTS = 0

UTILITY_ENVELOPE_RATE_CENTS_PER_SQFT = Decimal("37.5")
UTILITY_DUCT_RATE_CENTS_PER_UNIT = Decimal("1250")
UTILITY_DUCT_BASELINE = Decimal("4.0")
UTILITY_AIR_RATE_CENTS_PER_ACH = Decimal("1500")
UTILITY_AIR_BASELINE = Decimal("5.0")
UTILITY_INDEX_RATE_CENTS_PER_POINT = Decimal("2250")
UTILITY_INDEX_BASELINE = 60
UTILITY_PACKAGE_CAP_CENTS = 150000
UTILITY_LINE_ITEM_CODES = ["ENVELOPE", "DUCTS", "AIR", "INDEX"]

TAX_CREDIT_ISSUANCE_MAX_INDEX = 55
UTILITY_PROGRAM_ISSUANCE_MAX_INDEX = 50

# --- enum vocabularies ------------------------------------------------------
BUILDER_TYPES = ["PRODUCTION", "CUSTOM"]
BUILDER_STATUSES = ["ACTIVE", "SAMPLING_SUSPENDED"]
COMPLIANCE_PATH_PREFERENCES = ["ERI_PATH", "PRESCRIPTIVE_PATH"]
PLAN_MODEL_STATUSES = ["ACTIVE", "ARCHIVED"]
SAMPLING_ROLES = ["UNASSIGNED", "MEMBER", "TESTED", "REPRESENTED"]
CERT_LEVELS = ["RATER", "RATING_FIELD_INSPECTOR", "QA_DESIGNEE"]
CERTIFICATION_STATUSES = ["ACTIVE", "PROBATION", "SUSPENDED"]
EFFECTIVE_CERTIFICATION_STATUSES = ["ACTIVE", "PROBATION", "SUSPENDED", "EXPIRED"]
RATING_STAGES = ["PROJECTED", "ROUGH_IN_VERIFIED", "CONFIRMED", "REGISTERED", "VOID"]
COMPLIANCE_STATUSES = ["UNDETERMINED", "PASSING", "FAILING", "REMEDIATION_PENDING"]
QA_STATUSES = ["NOT_SELECTED", "QA_SELECTED", "QA_PASSED", "QA_FAILED"]
REGISTRY_STATUSES = ["NOT_SUBMITTED", "PENDING", "ACCEPTED", "REJECTED"]
COMPLIANCE_PATHS = ["ERI", "PERFORMANCE", "PRESCRIPTIVE", "NONE"]
CHECKPOINTS = ["ROUGH_IN", "FINAL"]
INSPECTION_STATUSES = ["SCHEDULED", "PASSED", "FAILED"]
TEST_TYPES = ["BLOWER_DOOR", "DUCT_LEAKAGE_TOTAL"]
TEST_RESULTS = ["PASS", "FAIL"]
SAMPLE_SET_STATUSES = [
    "FORMING",
    "SELECTED",
    "TESTED",
    "CLOSED_PASS",
    "FAILED_EXPANDED",
    "VOIDED_SAMPLING",
]
REVIEW_TYPES = ["FILE_REVIEW", "FIELD_REVIEW"]
QA_REVIEW_STATUSES = ["ASSIGNED", "COMPLETED"]
QA_RESULTS = ["PASS", "FAIL_MINOR", "FAIL_MAJOR"]
CORRECTIVE_ACTION_REASONS = ["THRESHOLD_FAILURE", "SAMPLE_SET_FAILURE", "QA_FINDING"]
CORRECTIVE_ACTION_STATUSES = ["OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "ESCALATED"]
PACKAGE_TYPES = ["TAX_CREDIT_45L", "UTILITY_PROGRAM"]
PACKAGE_STATUSES = ["DRAFT", "ISSUED", "REVOKED", "SUPERSEDED"]
REVOCATION_REASONS = ["QA_MAJOR_FAILURE", "RATING_VOID"]


# --- shared rounding helpers (§2.6) ----------------------------------------
def round_half_up(value, places: int) -> Decimal:
    """Round half-up to `places` decimal places, PRD §2.6."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def normalize_blower_door(measured_value, conditioned_volume_cuft) -> Decimal:
    """PRD §3.3: measured_value * 60 / conditioned_volume_cuft, half-up to 2dp."""
    raw = Decimal(str(measured_value)) * Decimal("60") / Decimal(str(conditioned_volume_cuft))
    return round_half_up(raw, 2)


def normalize_duct_leakage(measured_value, conditioned_floor_area_sqft) -> Decimal:
    """PRD §3.3: measured_value * 100 / conditioned_floor_area_sqft, half-up to 2dp."""
    raw = Decimal(str(measured_value)) * Decimal("100") / Decimal(str(conditioned_floor_area_sqft))
    return round_half_up(raw, 2)


def hers_index(
    *,
    climate_zone: str,
    code_edition: str,
    envelope_ua_btu_per_hr_f,
    conditioned_volume_cuft,
    conditioned_floor_area_sqft,
    bedrooms: int,
    hvac_efficiency_index,
    ach50,
    duct_leakage_cfm25_per_100sqft,
    pv_capacity_kw_dc=0,
) -> int:
    """The §3.1 HERS index routine, exact-decimal with a single final rounding."""
    term_one = Decimal(str(envelope_ua_btu_per_hr_f)) * ENVELOPE_LOAD_FACTOR[climate_zone]
    term_two = (
        BASE_LOAD_ACH_COEFFICIENT
        * Decimal(str(ach50))
        * Decimal(str(conditioned_volume_cuft))
        / BASE_LOAD_ACH_DIVISOR
    )
    term_three = (
        BASE_LOAD_DUCT_COEFFICIENT
        * Decimal(str(duct_leakage_cfm25_per_100sqft))
        * Decimal(str(conditioned_floor_area_sqft))
        / BASE_LOAD_DUCT_DIVISOR
    )
    base_load = term_one + term_two + term_three

    multiplier = EQUIP_MULT_INTERCEPT - EQUIP_MULT_SLOPE * Decimal(str(hvac_efficiency_index))
    multiplier = min(max(multiplier, EQUIP_MULT_FLOOR), EQUIP_MULT_CEILING)

    reference_load = REFERENCE_LOAD_AREA_COEFFICIENT * Decimal(
        str(conditioned_floor_area_sqft)
    ) + REFERENCE_LOAD_BEDROOM_COEFFICIENT * Decimal(str(bedrooms))

    raw_index = base_load * multiplier / reference_load * Decimal("100")

    pv_credit = min(
        PV_INDEX_CAP[code_edition],
        PV_CREDIT_POINTS_PER_KW * Decimal(str(pv_capacity_kw_dc)),
    )

    rounded = round_half_up(raw_index - pv_credit, 0)
    return max(int(rounded), 0)
