"""Program constants of the inclusionary-zoning compliance domain.

Every value here is declared by the PRD.  Money is always integer cents and every
rate is expressed in basis points where 10000 basis points == 100%.
"""

# --- logical clock -----------------------------------------------------------
# The server's logical clock reads exactly this instant before the first
# /_clock/set_current_utc call of a test.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- basis-point scale -------------------------------------------------------
BPS_SCALE = 10000
ONE_UNIT_BPS = 10000

THRESHOLDS = {
    # required_units_and_fraction: the residual fraction becomes a whole unit at
    # or above half a unit.
    "HALF_UNIT_BPS": 5000,
    # income_limit: annual limits are published to the whole dollar.
    "WHOLE_DOLLAR_CENTS": 100,
    # max_allowed_rent: 30% of monthly income is the rent burden standard.
    "RENT_BURDEN_BPS": 3000,
    # unit_mix_compliance: comparability floor and family-unit distribution floor.
    "COMPARABILITY_MIN_BPS": 8000,
    "MIN_FAMILY_UNIT_BPS": 5000,
    "FAMILY_UNIT_MIN_BEDROOMS": 2,
    # max_resale_price: capital-improvement credit ceiling.
    "IMPROVEMENT_CAP_BPS": 1000,
    # cure_penalty_and_deadline.
    "OVERCHARGE_MULTIPLIER": 3,
    "FLAT_MONTHLY_PENALTY_CENTS": 25000,
    "PENALTY_EXTENSION_THRESHOLD_CENTS": 100000,
    "CURE_BASE_DAYS": 30,
    "CURE_EXTENSION_DAYS": 15,
    "DAYS_PER_PENALTY_MONTH": 30,
    # monitoring_findings: a sitting household may grow to 140% of entry limit.
    "OVER_INCOME_TOLERANCE_BPS": 14000,
    # trust_fund_ledger: administrative use ceiling.
    "ADMIN_USE_CAP_BPS": 1000,
    # certification term and recertification window.
    "CERTIFICATION_TERM_DAYS": 365,
    "RECERT_WINDOW_DAYS": 30,
    # right of first refusal.
    "ROFR_WINDOW_DAYS": 30,
    # the SUBSTITUTION basis always prices exactly one unit equivalent.
    "SUBSTITUTION_EQUIVALENT_BPS": 10000,
}

# --- enum domains ------------------------------------------------------------
ZONING_DISTRICTS = ["R-2", "R-4", "C-2"]
COMPLIANCE_PATHS = ["ONSITE", "OFFSITE", "IN_LIEU_FEE", "LAND_DEDICATION"]
TENURES = ["RENTAL", "OWNERSHIP"]
AFFORDABILITY_LEVELS_BPS = [5000, 8000, 12000]
PREFERENCE_CATEGORIES = ["LIVE_WORK", "DISPLACED", "PUBLIC_EMPLOYEE"]
FEE_BASES = ["FULL", "FRACTIONAL", "SUBSTITUTION"]
ELIGIBLE_USES = [
    "AFFORDABLE_HOUSING_PRODUCTION",
    "RENTAL_SUBSIDY",
    "HOMEBUYER_ASSISTANCE",
    "ADMIN",
]
FINDING_TYPES = ["RENT_OVERCHARGE", "INCOME_OVER_LIMIT", "OCCUPANCY_UNVERIFIED"]
FUNDER_REPORT_BASES = ["ENTITLEMENT", "OCCUPANCY"]

# --- canonical program fixture literals -------------------------------------
# The ordinance vintage and AMI schedules used by the shared setup helpers.
CANONICAL_ORDINANCE_CODE = "IZ-2024-01"
CANONICAL_ORDINANCE_EFFECTIVE_DATE = "2024-01-01"
CANONICAL_MIN_PROJECT_UNITS_THRESHOLD = 10
CANONICAL_SET_ASIDE_BPS_BY_DISTRICT = {"R-2": 1000, "R-4": 1500, "C-2": 2000}
CANONICAL_GAP_BASIS_CENTS_BY_LEVEL = {
    "5000": 24000000,
    "8000": 18000000,
    "12000": 12000000,
}
CANONICAL_FEE_GAP_LEVEL_BPS = 5000
CANONICAL_SURCHARGE_BPS = 350
CANONICAL_SURCHARGE_CAP_CENTS = 5000000
CANONICAL_DISCOUNT_TIERS = [
    {"min_pre_discount_cents": 0, "discount_bps": 0},
    {"min_pre_discount_cents": 20000000, "discount_bps": 150},
    {"min_pre_discount_cents": 100000000, "discount_bps": 400},
]
CANONICAL_FEE_DUE_DAYS = 45
CANONICAL_ALTERNATIVE_PATHS = ["IN_LIEU_FEE", "OFFSITE"]

AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE = {
    "1": 9868000,
    "2": 11278000,
    "3": 12669800,
    "4": 14082000,
    "5": 15214000,
}
AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE = {
    "1": 10559000,
    "2": 12067000,
    "3": 13555700,
    "4": 15068000,
    "5": 16279000,
}
CANONICAL_UTILITY_ALLOWANCE_CENTS_BY_BEDROOMS = {
    "0": 8500,
    "1": 11000,
    "2": 14500,
    "3": 18000,
}

# Derived literals of the canonical program, pinned so that the tests never
# recompute what the PRD already determines.
INCOME_LIMIT_SIZE_3_AT_5000_BPS = 6334900
INCOME_LIMIT_SIZE_2_AT_5000_BPS = 5639000
MAX_ALLOWED_RENT_2BR_AT_5000_BPS = 143872
MAX_ALLOWED_RENT_1BR_AT_5000_BPS = 129975
RECERT_CEILING_SIZE_3_AT_5000_BPS = 8868860
