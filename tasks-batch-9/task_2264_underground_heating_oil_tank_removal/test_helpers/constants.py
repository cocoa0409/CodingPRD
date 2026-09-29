"""Domain constants the PRD pins by name or by value.

Every figure here is quoted from the PRD's own prose: the scoring factors of the
abandonment recommendation, the contamination action and gross levels, the soil
density and grid geometry, the disposal multipliers and mobilization charge, the
state deductible schedule and reimbursement cap tiers, the laboratory defaults
and the logical clock's startup instant.
"""

# --------------------------------------------------------------------------- #
# The logical site clock
# --------------------------------------------------------------------------- #
#: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# §3.1 — the removal-versus-abandonment recommendation
# --------------------------------------------------------------------------- #
#: Inches of cover treated as free before the depth factor starts to accrue.
DEPTH_FREE_INCHES = 24
#: Half a point per inch of cover beyond the free allowance.
DEPTH_POINTS_PER_INCH = 0.5
#: The depth factor is clamped into 0.0 .. 40.0.
DEPTH_FACTOR_MAX = 40.0
#: Clearance below which the foundation is considered at concern.
FOUNDATION_CONCERN_INCHES = 60
#: Three quarters of a point per inch of missing clearance.
PROXIMITY_POINTS_PER_INCH = 0.75
#: The proximity factor is clamped into 0.0 .. 30.0.
PROXIMITY_FACTOR_MAX = 30.0
#: Awarded in full when any part of the tank lies beneath a structure.
UNDER_STRUCTURE_POINTS = 35.0
#: The two-step capacity tier.
CAPACITY_LARGE_GALLONS = 1000
CAPACITY_LARGE_POINTS = 15.0
CAPACITY_MEDIUM_GALLONS = 550
CAPACITY_MEDIUM_POINTS = 8.0
#: Awarded for a steel shell; fibreglass earns nothing.
STEEL_MATERIAL_POINTS = 10.0
#: The raw sum of the five clamped factors is capped here before rounding.
METHOD_SCORE_MAX = 100.0
#: `recommended_method` is ABANDONMENT_IN_PLACE at a score of at least this.
ABANDONMENT_SCORE_THRESHOLD = 55.00

# --------------------------------------------------------------------------- #
# §3.2 — the homeowner response window
# --------------------------------------------------------------------------- #
#: "`expires_at` derived as three days later — the response window is 72 hours".
DISCLOSURE_WINDOW_HOURS = 72

# --------------------------------------------------------------------------- #
# §3.3 — permit validity and the fire-marshal lead time
# --------------------------------------------------------------------------- #
#: "`expires_at` is derived as exactly 180 days after issuance".
PERMIT_VALIDITY_DAYS = 180
#: The two-day statutory wait before ground may be broken.
FIRE_MARSHAL_NOTICE_LEAD_HOURS = 48

# --------------------------------------------------------------------------- #
# §3.4 — the buffered crew calendar
# --------------------------------------------------------------------------- #
#: Default travel-and-decontamination allowance on both ends of a booking.
DEFAULT_MOBILIZATION_BUFFER_MINUTES = 90

# --------------------------------------------------------------------------- #
# §3.6 — laboratory operating parameters and contamination thresholds
# --------------------------------------------------------------------------- #
DEFAULT_ACCREDITED = True
DEFAULT_COMMITTED_TURNAROUND_HOURS = 72
DEFAULT_HOLDING_TIME_HOURS = 336
DEFAULT_MAX_CONCURRENT_ANALYSES = 2
#: Hours are computed from seconds, so the divisor is pinned.
SECONDS_PER_HOUR = 3600.0

#: The action levels: strictly exceeding either of these is an exceedance.
TPH_ACTION_LEVEL_MG_KG = 500.0
BENZENE_ACTION_LEVEL_MG_KG = 0.5
#: The gross levels.
TPH_GROSS_LEVEL_MG_KG = 5000.0
BENZENE_GROSS_LEVEL_MG_KG = 5.0

# --------------------------------------------------------------------------- #
# §3.5 and §3.7 — the two remediation-volume variants
# --------------------------------------------------------------------------- #
#: The grid cell each sample point is taken to represent, in square feet.
GRID_CELL_SQFT = 100.0
#: Cubic feet in a cubic yard.
CUBIC_FEET_PER_CUBIC_YARD = 27.0
#: Inches in a foot, for the depth conversion.
INCHES_PER_FOOT = 12
#: Tons per cubic yard, the FINAL_SURVEYED divisor.
SOIL_DENSITY_TONS_PER_CUBIC_YARD = 1.35

# --------------------------------------------------------------------------- #
# §3.7 — remediation cost
# --------------------------------------------------------------------------- #
#: The flat mobilization charge, added only once remediation has begun.
BASE_MOBILIZATION_CENTS = 185000
#: Disposal loading by class.
DISPOSAL_MULTIPLIER_NON_HAZARDOUS = 1.0
DISPOSAL_MULTIPLIER_HAZARDOUS = 1.85
DISPOSAL_MULTIPLIERS = {
    "NON_HAZARDOUS": DISPOSAL_MULTIPLIER_NON_HAZARDOUS,
    "HAZARDOUS": DISPOSAL_MULTIPLIER_HAZARDOUS,
}

# --------------------------------------------------------------------------- #
# §3.1 and §3.9 — the state deductible schedule
# --------------------------------------------------------------------------- #
STATE_DEDUCTIBLE_CENTS = {
    "NJ": 50000,
    "NY": 100000,
    "CT": 25000,
}

# --------------------------------------------------------------------------- #
# §3.9 — trust-fund eligibility
# --------------------------------------------------------------------------- #
#: Tier boundaries on the gross figure.
CAP_TIER_1_MAX_CENTS = 5000000
CAP_TIER_2_MAX_CENTS = 12000000
#: The reimbursement ceilings the tiers select.
CAP_TIER_1_CENTS = 4000000
CAP_TIER_2_CENTS = 9000000
CAP_TIER_3_CENTS = 12500000
#: The fund's administrative rate.
ADMIN_FEE_RATE = 0.035
#: "the fund permits at most two rounds of questions".
MAX_INFO_REQUESTS = 2

# --------------------------------------------------------------------------- #
# §3.1 — property coverage defaults
# --------------------------------------------------------------------------- #
DEFAULT_FIRST_PARTY_COVERAGE_LIMIT_CENTS = 2000000
DEFAULT_THIRD_PARTY_SUBLIMIT_CENTS = 5000000

# --------------------------------------------------------------------------- #
# §3.1 — tank project scope defaults
# --------------------------------------------------------------------------- #
DEFAULT_BASELINE_SCOPE_CUBIC_YARDS = 8.0
DEFAULT_EXCAVATION_LIMIT_CUBIC_YARDS = 40.0

# --------------------------------------------------------------------------- #
# §3.8 — the waterfall bucket order
# --------------------------------------------------------------------------- #
WATERFALL_BUCKET_ORDER = ["FIRST_PARTY", "THIRD_PARTY_LIABILITY", "HOMEOWNER"]

# --------------------------------------------------------------------------- #
# §3.9 — the seven closure blocker codes
# --------------------------------------------------------------------------- #
BLOCKER_CONTAMINATION_NOT_CLEARED = "CONTAMINATION_NOT_CLEARED"
BLOCKER_SAMPLES_PENDING = "SAMPLES_PENDING"
BLOCKER_INVALIDATED_SAMPLE_WITHOUT_RETEST = "INVALIDATED_SAMPLE_WITHOUT_RETEST"
BLOCKER_OPEN_CHANGE_ORDER = "OPEN_CHANGE_ORDER"
BLOCKER_CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED = (
    "CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED"
)
BLOCKER_PERMIT_REVOKED = "PERMIT_REVOKED"
BLOCKER_FIELD_WORK_INCOMPLETE = "FIELD_WORK_INCOMPLETE"

BLOCKER_CODES = [
    BLOCKER_CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED,
    BLOCKER_CONTAMINATION_NOT_CLEARED,
    BLOCKER_FIELD_WORK_INCOMPLETE,
    BLOCKER_INVALIDATED_SAMPLE_WITHOUT_RETEST,
    BLOCKER_OPEN_CHANGE_ORDER,
    BLOCKER_PERMIT_REVOKED,
    BLOCKER_SAMPLES_PENDING,
]

# --------------------------------------------------------------------------- #
# §3.9 — eligibility finding codes
# --------------------------------------------------------------------------- #
FINDING_SUPERSEDED_BY_FINAL_SETTLEMENT = "SUPERSEDED_BY_FINAL_SETTLEMENT"
FINDING_NFA_RESCINDED_REVALIDATION_REQUIRED = "NFA_RESCINDED_REVALIDATION_REQUIRED"

# --------------------------------------------------------------------------- #
# Cascade reason codes
# --------------------------------------------------------------------------- #
REVOCATION_REASON_HOMEOWNER_DECLINED = "HOMEOWNER_DECLINED"
ABORT_REASON_PROJECT_VOIDED = "PROJECT_VOIDED"
ABORT_REASON_PERMIT_REVOKED = "PERMIT_REVOKED"
QC_FLAG_NONE = "NONE"
QC_FLAG_HOLDING_TIME_EXCEEDED = "HOLDING_TIME_EXCEEDED"
QC_FLAG_RESULT_RETRACTED = "RESULT_RETRACTED"

# --------------------------------------------------------------------------- #
# §2.3 — pagination bounds
# --------------------------------------------------------------------------- #
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0
