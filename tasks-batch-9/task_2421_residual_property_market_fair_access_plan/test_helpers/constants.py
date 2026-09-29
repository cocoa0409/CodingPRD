"""Domain constants for the Residual Property Fair Access Plan API.

Every literal here is transcribed from the PRD under test: role names, enum
members, the logical-clock origin, the premium ladder's factors and floors, the
territory posture thresholds, the refund fee tiers and the assessment credit
unit.  Nothing is invented and nothing is derived from an implementation.
"""

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

BASE_PATH = "/fair-plan"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1) — "The eight declared roles are PlanAdmin, Producer,
# Underwriter, Inspector, RateAnalyst, Regulator, MemberInsurerUser, and
# Policyholder."
# ---------------------------------------------------------------------------

ROLE_PLAN_ADMIN = "PlanAdmin"
ROLE_PRODUCER = "Producer"
ROLE_UNDERWRITER = "Underwriter"
ROLE_INSPECTOR = "Inspector"
ROLE_RATE_ANALYST = "RateAnalyst"
ROLE_REGULATOR = "Regulator"
ROLE_MEMBER_INSURER_USER = "MemberInsurerUser"
ROLE_POLICYHOLDER = "Policyholder"

ALL_ROLES = (
    ROLE_PLAN_ADMIN,
    ROLE_PRODUCER,
    ROLE_UNDERWRITER,
    ROLE_INSPECTOR,
    ROLE_RATE_ANALYST,
    ROLE_REGULATOR,
    ROLE_MEMBER_INSURER_USER,
    ROLE_POLICYHOLDER,
)

# Entity-backed roles: X-User-ID is the id of a persisted row (PRD 2.1).
ENTITY_BACKED_ROLES = (
    ROLE_PRODUCER,
    ROLE_MEMBER_INSURER_USER,
    ROLE_POLICYHOLDER,
)

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6)
# ---------------------------------------------------------------------------

CLOCK_ORIGIN = "2026-08-01T00:00:00Z"
# The instant every fixture pins the clock to before building state.
CLOCK_BASE = "2026-09-01T00:00:00Z"
CLOCK_BASE_DATE = "2026-09-01"

# ---------------------------------------------------------------------------
# Territory posture (PRD 2.7)
# ---------------------------------------------------------------------------

PERIL_HURRICANE = "HURRICANE"
PERIL_WILDFIRE = "WILDFIRE"
PERIL_EARTHQUAKE = "EARTHQUAKE"
PERILS = (PERIL_HURRICANE, PERIL_WILDFIRE, PERIL_EARTHQUAKE)

ZONE_STATUS_OPEN = "OPEN"
ZONE_STATUS_RESTRICTED = "RESTRICTED"
ZONE_STATUS_CLOSED = "CLOSED"

ZONE_CLOSED_RATIO = "1.0000"
ZONE_RESTRICTED_RATIO = "0.8500"
DEFAULT_RESTRICTED_MIN_CONDITION_SCORE = 70

# ---------------------------------------------------------------------------
# Member insurers / producers (PRD 3.1)
# ---------------------------------------------------------------------------

MEMBER_STATUS_ACTIVE = "ACTIVE"
MEMBER_STATUS_RUNOFF = "RUNOFF"
MEMBER_STATUS_WITHDRAWN = "WITHDRAWN"

COMMISSION_TIER_STANDARD = "STANDARD"
COMMISSION_TIER_PREFERRED = "PREFERRED"
COMMISSION_BPS_STANDARD = 1000
COMMISSION_BPS_PREFERRED = 1250
BPS_DIVISOR = 10000

AGREEMENT_STATUS_PENDING = "PENDING"
AGREEMENT_STATUS_APPOINTED = "APPOINTED"
AGREEMENT_STATUS_SUSPENDED = "SUSPENDED"
AGREEMENT_STATUS_TERMINATED = "TERMINATED"

PRODUCER_ACTION_SUSPEND = "SUSPEND"
PRODUCER_ACTION_REINSTATE = "REINSTATE"
PRODUCER_ACTION_TERMINATE = "TERMINATE"

# ---------------------------------------------------------------------------
# Rate filings (PRD 3.2)
# ---------------------------------------------------------------------------

PACKAGE_BASIC_FIRE_EO = "BASIC_FIRE_EO"
PACKAGE_EXTENDED_WIND = "EXTENDED_WIND"

FILING_STATUS_FILED = "FILED"
FILING_STATUS_APPROVED = "APPROVED"
FILING_STATUS_DISAPPROVED = "DISAPPROVED"
FILING_STATUS_SUPERSEDED = "SUPERSEDED"

DECISION_APPROVE = "APPROVE"
DECISION_DISAPPROVE = "DISAPPROVE"

RATE_FLOOR_DIFFERENTIAL = "0.1000"
FILING_QUIET_BUFFER_DAYS = 30

# ---------------------------------------------------------------------------
# Property / application (PRD 3.3)
# ---------------------------------------------------------------------------

CONSTRUCTION_FRAME = "FRAME"
CONSTRUCTION_MASONRY = "MASONRY"
CONSTRUCTION_MOBILE = "MOBILE"

OCCUPANCY_OWNER = "OWNER_OCCUPIED"
OCCUPANCY_TENANT = "TENANT_OCCUPIED"
OCCUPANCY_VACANT = "VACANT"

DWELLING_LIMIT_CEILING_CENTS = 150_000_000

APP_STATUS_DRAFT = "DRAFT"
APP_STATUS_SUBMITTED = "SUBMITTED"
APP_STATUS_ELIGIBILITY_HELD = "ELIGIBILITY_HELD"
APP_STATUS_INSPECTION_PENDING = "INSPECTION_PENDING"
APP_STATUS_IMPROVEMENTS_REQUIRED = "IMPROVEMENTS_REQUIRED"
APP_STATUS_APPROVED_TO_BIND = "APPROVED_TO_BIND"
APP_STATUS_BOUND = "BOUND"
APP_STATUS_DECLINED = "DECLINED"
APP_STATUS_WITHDRAWN = "WITHDRAWN"

HOLD_REASON_INSUFFICIENT_DECLINATIONS = "INSUFFICIENT_DECLINATIONS"
HOLD_REASON_BIND_WINDOW_LAPSED = "BIND_WINDOW_LAPSED"
DECLINE_REASON_INSPECTION_FAILED = "INSPECTION_FAILED"

REASON_CAT_EXPOSURE = "CAT_EXPOSURE"
REASON_CONDITION = "CONDITION"
REASON_LOSS_HISTORY = "LOSS_HISTORY"
REASON_NON_RENEWAL = "NON_RENEWAL"
REASON_APPETITE = "APPETITE"

ELIGIBILITY_DECISION_ADVANCE = "ADVANCE"
ELIGIBILITY_DECISION_DECLINE = "DECLINE"

# ---------------------------------------------------------------------------
# Declination sufficiency (PRD 3.4)
# ---------------------------------------------------------------------------

DECLINATION_LOOKBACK_DAYS = 60
DECLINATION_SUFFICIENCY_MINIMUM = 3

# ---------------------------------------------------------------------------
# Inspection and remediation (PRD 3.5)
# ---------------------------------------------------------------------------

INSPECTION_RESULT_PENDING = "PENDING"
INSPECTION_RESULT_PASS = "PASS"
INSPECTION_RESULT_PASS_WITH_CONDITIONS = "PASS_WITH_CONDITIONS"
INSPECTION_RESULT_FAIL = "FAIL"

REQUIREMENT_CODE_ROOF = "ROOF_REPLACEMENT"
REQUIREMENT_CODE_ELECTRICAL = "ELECTRICAL_UPDATE"
REQUIREMENT_CODE_DEFENSIBLE_SPACE = "DEFENSIBLE_SPACE"
REQUIREMENT_CODE_VACANCY_CURE = "VACANCY_CURE"

SEVERITY_MAJOR = "MAJOR"
SEVERITY_MINOR = "MINOR"

REQUIREMENT_STATUS_OPEN = "OPEN"
REQUIREMENT_STATUS_EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
REQUIREMENT_STATUS_CLEARED = "CLEARED"
REQUIREMENT_STATUS_WAIVED = "WAIVED"

REQUIREMENT_DUE_DAYS = 45
BIND_WINDOW_DAYS = 30
INSPECTION_STALENESS_DAYS = 90

# ---------------------------------------------------------------------------
# Premium ladder (PRD 3.6)
# ---------------------------------------------------------------------------

CONSTRUCTION_FACTORS = {
    CONSTRUCTION_FRAME: "1.25",
    CONSTRUCTION_MASONRY: "1.00",
    CONSTRUCTION_MOBILE: "1.60",
}
OCCUPANCY_FACTORS = {
    OCCUPANCY_OWNER: "1.00",
    OCCUPANCY_TENANT: "1.15",
    OCCUPANCY_VACANT: "1.45",
}
PACKAGE_FACTORS = {
    PACKAGE_BASIC_FIRE_EO: "1.00",
    PACKAGE_EXTENDED_WIND: "1.35",
}

CAT_SURCHARGE_THRESHOLD_RATIO = "0.60"
CAT_SURCHARGE_SLOPE = "0.45"
CAT_SURCHARGE_CAP = "0.25"

CONDITION_TIER_TOP_SCORE = 85          # >= 85 -> -10%
CONDITION_TIER_MID_SCORE = 70          # >= 70 -> -5%
CONDITION_TIER_NEUTRAL_SCORE = 50      # >= 50 -> 0%, below 50 -> +15%

IMPROVEMENT_CREDIT_PER_MAJOR = "0.04"
IMPROVEMENT_CREDIT_CAP = "0.08"

MINIMUM_ANNUAL_PREMIUM_CENTS = 35_000

POLICY_TERM_DAYS = 365

EXCLUDED_PERILS_BASIC_FIRE_EO = ["WINDSTORM", "HAIL", "WATER_DAMAGE", "THEFT", "LIABILITY"]
EXCLUDED_PERILS_EXTENDED_WIND = ["WATER_DAMAGE", "THEFT", "LIABILITY"]

PREMIUM_VARIANT_PROVISIONAL_QUOTE = "PROVISIONAL_QUOTE"
PREMIUM_VARIANT_VOLUNTARY_EQUIVALENT = "VOLUNTARY_EQUIVALENT"
PREMIUM_VARIANT_BOUND_FINAL = "BOUND_FINAL"
PREMIUM_VARIANT_RENEWAL_FINAL = "RENEWAL_FINAL"

# ---------------------------------------------------------------------------
# Policy state dimensions (PRD 3.6 / 3.7 / 3.8)
# ---------------------------------------------------------------------------

COVERAGE_STATUS_BOUND = "BOUND"
COVERAGE_STATUS_IN_FORCE = "IN_FORCE"
COVERAGE_STATUS_CANCELLED = "CANCELLED"
COVERAGE_STATUS_EXPIRED = "EXPIRED"
COVERAGE_STATUS_TAKEN_OUT = "TAKEN_OUT"

DEPOP_STATUS_NOT_OFFERED = "NOT_OFFERED"
DEPOP_STATUS_OFFER_OUTSTANDING = "OFFER_OUTSTANDING"
DEPOP_STATUS_ELECTED_TAKEOUT = "ELECTED_TAKEOUT"
DEPOP_STATUS_ELECTED_RETAIN = "ELECTED_RETAIN"

CANCEL_REASON_POLICYHOLDER_REQUEST = "POLICYHOLDER_REQUEST"
CANCEL_REASON_PLAN_INITIATED = "PLAN_INITIATED"
CANCEL_REASON_TAKEOUT_ELECTION = "TAKEOUT_ELECTION"

REFUND_VARIANT_PRO_RATA = "PRO_RATA"
REFUND_VARIANT_SHORT_RATE = "SHORT_RATE"
SHORT_RATE_MULTIPLIER = "0.90"

CANCELLATION_FEE_TIER_1_LIMIT_CENTS = 50_000
CANCELLATION_FEE_TIER_1_CENTS = 2_500
CANCELLATION_FEE_TIER_2_LIMIT_CENTS = 200_000
CANCELLATION_FEE_TIER_2_CENTS = 5_000
CANCELLATION_FEE_RATE = "0.03"

# ---------------------------------------------------------------------------
# Take-out offers (PRD 3.8)
# ---------------------------------------------------------------------------

OFFER_STATUS_OUTSTANDING = "OUTSTANDING"
OFFER_STATUS_ACCEPTED = "ACCEPTED"
OFFER_STATUS_DECLINED = "DECLINED"
OFFER_STATUS_WITHDRAWN = "WITHDRAWN"
OFFER_STATUS_EXPIRED = "EXPIRED"

ELECTION_ACCEPT = "ACCEPT"
ELECTION_DECLINE = "DECLINE"

OFFER_COMPARABILITY_MULTIPLIER = "1.15"

# ---------------------------------------------------------------------------
# Assessments (PRD 3.9)
# ---------------------------------------------------------------------------

BASIS_MARKET_SHARE = "MARKET_SHARE"
BASIS_PREMIUM_VOLUME = "PREMIUM_VOLUME"

EVENT_STATUS_DRAFT = "DRAFT"
EVENT_STATUS_ALLOCATED = "ALLOCATED"
EVENT_STATUS_INVOICED = "INVOICED"
EVENT_STATUS_SETTLED = "SETTLED"
EVENT_STATUS_CANCELLED = "CANCELLED"

ALLOCATION_STATUS_PENDING = "PENDING"
ALLOCATION_STATUS_PAID = "PAID"
ALLOCATION_STATUS_ABATED = "ABATED"

CREDIT_UNIT_CENTS = 500_000
CREDIT_OFFSET_SHARE = "0.50"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
