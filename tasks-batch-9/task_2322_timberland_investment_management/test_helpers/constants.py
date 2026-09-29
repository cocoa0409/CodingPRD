"""Numeric and enumeration constants pinned by the Timberland Investment Management PRD.

Every value here is stated literally in the PRD prose and is reproduced so that
test expectations read in domain language rather than as bare magic numbers.
"""

# --- Logical clock (PRD §2.5) ---------------------------------------------
# "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# "A year is 365 days everywhere a year-length constant is needed."
DAYS_PER_YEAR = 365

# --- Market access tiers (PRD §3.1) --------------------------------------
TIER_A_MAX_MILES = 40
TIER_B_MAX_MILES = 80
TIER_C_MAX_MILES = 140
MARKET_ACCESS_DISCOUNT_PCT = {
    "TIER_A": 0.0,
    "TIER_B": 4.5,
    "TIER_C": 9.0,
    "TIER_D": 15.0,
}

# --- Cruise expansion (PRD §3.1) ----------------------------------------
MIN_PLOTS_FOR_NORMAL_CONFIDENCE = 5
LOW_CONFIDENCE_HAIRCUT_PCT = 8

# --- Growth projection (PRD §3.2) ---------------------------------------
PERIODIC_GROWTH_PCT = {
    "LOBLOLLY_PINE": 4.2,
    "DOUGLAS_FIR": 3.1,
    "NORTHERN_HARDWOOD": 2.4,
}
MAI_TONS_PER_ACRE_YEAR = {
    "LOBLOLLY_PINE": 2.1,
    "DOUGLAS_FIR": 1.6,
    "NORTHERN_HARDWOOD": 0.9,
}
HARVEST_PERIODS = 3
PERIOD_HARVEST_PCT = 25
MIDPERIOD_OFFSET = 0.5
REC_INCOME_MULTIPLE = 6.5

# --- Acquisition fee tiers (PRD §3.2) -----------------------------------
ACQ_FEE_BREAK_1 = 1500000.00
ACQ_FEE_BREAK_2 = 3250000.00
ACQ_FEE_PCT_BELOW_BREAK_1 = 1.50
ACQ_FEE_PCT_BETWEEN_BREAKS = 1.00
ACQ_FEE_PCT_AT_OR_ABOVE_BREAK_2 = 0.75

# --- Revision loop (PRD §3.2) -------------------------------------------
MAX_REVISION_ROUNDS = 2

# --- Appraisal (PRD §3.3) -----------------------------------------------
STALE_APPRAISAL_HAIRCUT_PCT = 12
APPRAISAL_STALE_AFTER_DAYS = 365

# --- Harvest revenue (PRD §3.4) -----------------------------------------
PRODUCT_MIX_FACTOR = {
    "SAWTIMBER": 1.00,
    "MIXED": 0.82,
    "PULPWOOD": 0.61,
}
LOGGING_COST_USD_PER_TON = 12.75
HAUL_RATE_USD_PER_TON_MILE = 0.145
MAX_BILLABLE_HAUL_MILES = 90
SEVERANCE_TAX_PCT = 2.5
MIN_SEVERANCE_TAX_USD = 250.00
REENTRY_BUFFER_MONTHS = 24

# --- Carbon (PRD §3.5) --------------------------------------------------
CARBON_BUFFER_POOL_PCT = 18
BUFFER_CURE_COST_USD_PER_TON = 14.00

# --- Recreational leasing (PRD §3.6) ------------------------------------
MAX_LEASE_COVERAGE_PCT = 80

# --- Certification (PRD §3.7) -------------------------------------------
MAJOR_SUSPENSION_THRESHOLD = 2

# --- Hazard, insurance and salvage (PRD §3.8) ---------------------------
WEIGHT_WILDFIRE = 0.45
WEIGHT_INSECT = 0.30
WEIGHT_WEATHER = 0.25
REGION_WILDFIRE_MULT = {
    "SOUTH": 1.00,
    "WEST": 1.25,
    "NORTHEAST": 0.80,
}
SPECIES_INSECT_MULT = {
    "LOBLOLLY_PINE": 1.15,
    "DOUGLAS_FIR": 1.00,
    "NORTHERN_HARDWOOD": 1.00,
}
NO_STAND_INSECT_MULT = 1.00
HAZARD_INDEX_CAP = 100.00
BASE_RATE_BPS = 38
MIN_PREMIUM_USD = 1500.00
TRAILING_CLAIM_WINDOW_DAYS = 1095
SALVAGE_RECOVERY_PCT = {
    "WILDFIRE": 35,
    "INSECT": 55,
    "WIND_STORM": 70,
    "ICE_STORM": 60,
}
INDEMNITY_RATE_USD_PER_TON = 22.50
INSURANCE_INDEMNITY_PCT = 60

# --- HBU disposition (PRD §3.9) -----------------------------------------
HBU_COMMISSION_PCT = 3.5
MIN_RETAINED_ACRES = 5

# --- Basis points (PRD §2.11) -------------------------------------------
BPS_SCALE = 10000

# --- Enumerations -------------------------------------------------------
REGION_CODES = ("SOUTH", "WEST", "NORTHEAST")
CERTIFICATION_SCHEMES = ("SFI", "FSC", "NONE")
SPECIES_CODES = ("LOBLOLLY_PINE", "DOUGLAS_FIR", "NORTHERN_HARDWOOD")
GROWTH_VARIANTS = ("YIELD_TABLE", "MAI_LINEAR")
PRODUCT_MIXES = ("SAWTIMBER", "MIXED", "PULPWOOD")
CARBON_REGISTRIES = ("ACR", "CAR", "VERRA")
APPRAISAL_METHODOLOGIES = ("INCOME", "MARKET", "COST")
AUDIT_TYPES = ("SURVEILLANCE", "RECERTIFICATION")
FINDING_SEVERITIES = ("MAJOR", "MINOR", "OBSERVATION")
EVENT_TYPES = ("WILDFIRE", "INSECT", "WIND_STORM", "ICE_STORM")
INSURANCE_RATING_BASES = ("ACTUARIAL", "EXPERIENCE_RATED")

PROPERTY_STATUSES = (
    "PROSPECT",
    "UNDER_UNDERWRITING",
    "APPROVED_FOR_BID",
    "PASSED",
    "OWNED",
    "HBU_MARKETED",
)
APPRAISAL_STATUSES = ("NONE", "SUBMITTED", "SIGNED", "STALE")
CERTIFICATION_POSTURES = ("CERTIFIED", "CONDITIONAL", "SUSPENDED", "UNCERTIFIED")
HARVEST_PLAN_STATUSES = ("ALIGNED", "REPLAN_REQUIRED")
STAND_STATUSES = ("CRUISE_OPEN", "INVENTORIED", "SALVAGE_PENDING", "DISPOSED")
CRUISE_CONFIDENCES = ("NONE", "LOW", "NORMAL")
UNDERWRITING_CASE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "REJECTED",
    "WITHDRAWN",
)
HARVEST_BLOCK_STATUSES = (
    "RESERVED",
    "COMMITTED",
    "COMPLETED",
    "CANCELLED",
    "VOIDED",
)
VOIDED_REASONS = ("HAZARD_LOSS", "HBU_WITHDRAWAL")
CARBON_PROJECT_STATUSES = (
    "DRAFT",
    "VALIDATION",
    "REGISTERED",
    "REVERSAL_PENDING",
    "TERMINATED",
)
CARBON_DEDICATION_STATUSES = ("PENDING", "ACTIVE", "REDUCED", "RELEASED")
HBU_PARCEL_STATUSES = (
    "IDENTIFIED",
    "LISTED",
    "UNDER_CONTRACT",
    "CLOSED",
    "WITHDRAWN",
)
LEASE_STATUSES = ("PENDING", "ACTIVE", "TERMINATED", "EXPIRED")
AUDIT_STATUSES = (
    "SCHEDULED",
    "FIELD_WORK",
    "FINDINGS_ISSUED",
    "CAR_REVIEW",
    "SUSPENDED",
    "CLOSED_CONFORMING",
)
FINDING_STATUSES = ("OPEN", "CAR_SUBMITTED", "CLOSED")
HAZARD_EVENT_STATUSES = ("REPORTED", "SETTLED")

# --- Pagination defaults (PRD §2.3) -------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
