"""Business constants for the hotel pre-opening program management API.

Every value here is stated in the PRD. Tests import these names rather than
repeating magic numbers so that a reader can trace an assertion back to the
paragraph that fixes the number.
"""

# ─── API surface ──────────────────────────────────────────────────────────────

API_PREFIX = "/pre-opening"
CLOCK_PATH = "/_clock/set_current_utc"

# The logical clock starts here on a freshly started server.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# The instant every scenario in this suite anchors on.
DEFAULT_NOW = "2026-09-01T00:00:00Z"

# ─── Program state dimensions ─────────────────────────────────────────────────

SCHEDULE_STATES = [
    "PLANNING",
    "BASELINED",
    "CONSTRUCTION_COMPLETE",
    "LICENSING",
    "SOFT_OPENING",
    "STABILIZED",
]

COMMERCIAL_STATES = [
    "BOOKING_CLOSED",
    "BOOKING_OPEN",
    "BOOKING_SUSPENDED",
    "SELLING_STABILIZED",
]

READINESS_POSTURES = ["MOBILIZING", "ON_TRACK", "RESTRICTED", "FROZEN"]

# Delivery states from which booking acceptance may be opened.
BOOKING_OPENABLE_SCHEDULE_STATES = ["CONSTRUCTION_COMPLETE", "LICENSING", "SOFT_OPENING"]

# Delivery states in which a milestone may be started.
MILESTONE_STARTABLE_SCHEDULE_STATES = ["BASELINED", "CONSTRUCTION_COMPLETE", "LICENSING"]

# ─── Child entity states ──────────────────────────────────────────────────────

MILESTONE_STATES = ["NOT_STARTED", "IN_PROGRESS", "BLOCKED", "COMPLETE", "REOPENED"]
PERMIT_STATES = ["DRAFT", "SUBMITTED", "DEFICIENT", "ISSUED"]
SYSTEM_STATES = ["PLANNED", "TESTING", "CERTIFIED", "FAILED"]
HIRE_STATES = ["OFFERED", "ACCEPTED", "DECLINED", "ONBOARDED", "WITHDRAWN"]
TRAINING_SESSION_STATES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
OSE_ORDER_STATES = ["COMMITTED", "STORED", "CANCELLED"]
RESERVATION_BLOCK_STATES = [
    "ACCEPTED",
    "GUARANTEED",
    "AT_RISK",
    "RELOCATED",
    "CANCELLED",
    "HONORED",
]
PUNCH_ITEM_STATES = ["OPEN", "READY_FOR_VERIFICATION", "VERIFIED", "REJECTED"]
PLAN_READINESS_FLAGS = ["NOT_READY", "READY"]
TEST_RUN_RESULTS = ["PASSED", "FAILED"]

# ─── Enumerations used in request payloads ────────────────────────────────────

PERMIT_TYPES = [
    "CERTIFICATE_OF_OCCUPANCY",
    "LIQUOR_LICENSE",
    "FOOD_SERVICE",
    "ELEVATOR",
    "FIRE_ALARM",
    "SIGNAGE",
]

# Exactly four permit types are opening-mandatory.
MANDATORY_PERMIT_TYPES = [
    "CERTIFICATE_OF_OCCUPANCY",
    "LIQUOR_LICENSE",
    "FOOD_SERVICE",
    "ELEVATOR",
]
MANDATORY_PERMIT_COUNT = 4

NON_MANDATORY_PERMIT_TYPES = ["FIRE_ALARM", "SIGNAGE"]

# Permit sequencing: a type may only be submitted once each listed
# prerequisite type of the same program is ISSUED.
PERMIT_PREREQUISITES = {
    "CERTIFICATE_OF_OCCUPANCY": ["ELEVATOR"],
    "LIQUOR_LICENSE": ["CERTIFICATE_OF_OCCUPANCY", "FOOD_SERVICE"],
    "FOOD_SERVICE": [],
    "ELEVATOR": [],
    "FIRE_ALARM": [],
    "SIGNAGE": [],
}

# The order in which the four mandatory permits can legally be issued.
MANDATORY_PERMIT_ISSUE_ORDER = [
    "ELEVATOR",
    "FOOD_SERVICE",
    "CERTIFICATE_OF_OCCUPANCY",
    "LIQUOR_LICENSE",
]

SYSTEM_TYPES = ["PMS", "POS", "KEY", "REVENUE"]

DEPARTMENTS = ["ROOMS", "FOOD_BEVERAGE", "ENGINEERING", "SALES_MARKETING", "ADMIN"]

# A training session's department may also be ALL, which is its default.
SESSION_DEPARTMENT_ALL = "ALL"
SESSION_DEPARTMENTS = [SESSION_DEPARTMENT_ALL] + DEPARTMENTS

BUDGET_CATEGORIES = ["PAYROLL", "MARKETING", "SETUP"]

PUNCH_SEVERITIES = ["CRITICAL", "MAJOR", "MINOR"]
DEPENDENCY_TYPES = ["FINISH_START", "START_START"]

AT_RISK_REASONS = ["PERMIT_DEFICIENCY", "CRITICAL_PUNCH_OPEN"]

# Milestone codes that carry program-level meaning.
CODE_CONSTRUCTION_COMPLETE = "CONSTRUCTION_COMPLETE"
CODE_CO_ISSUANCE = "CO_ISSUANCE"

# ─── Tuning defaults on PreOpeningProgram ─────────────────────────────────────

DEFAULT_LICENSING_BUFFER_DAYS = 14
DEFAULT_REWORK_BUFFER_DAYS = 3
DEFAULT_SLIP_TOLERANCE_DAYS = 10
DEFAULT_STABILIZATION_WINDOW_DAYS = 30

# ─── Readiness posture arithmetic ─────────────────────────────────────────────

WEIGHT_SYSTEMS = 0.30
WEIGHT_STAFFING = 0.25
WEIGHT_PERMIT = 0.25
WEIGHT_SCHEDULE = 0.20

# schedule_term = 1.0 - schedule_slip_days / 30, floored at 0.0
SLIP_NORMALIZER_DAYS = 30

# readiness_score at or above this floor, with all four mandatory permits
# issued and nothing restricting, is ON_TRACK.
ON_TRACK_SCORE_FLOOR = 0.85

# Ratios and scores are rounded half up to four decimal places.
RATIO_DECIMAL_PLACES = 4

# ─── System test aggregation ──────────────────────────────────────────────────

CERTIFY_PASS_RATE_FLOOR = 0.95
FAILED_PASS_RATE_CEILING = 0.50

# ─── Department readiness ─────────────────────────────────────────────────────

# readiness_flag flips to READY once onboarded_count * 100 >= headcount_target * 80.
READINESS_THRESHOLD_PERCENT = 80

# ─── Contingency liability tiers, keyed on the pre-fee relocation base ────────

CONTINGENCY_TIER_LOW_LIMIT_CENTS = 500000
CONTINGENCY_TIER_LOW_RATE = 0.05
CONTINGENCY_TIER_MID_LIMIT_CENTS = 2000000
CONTINGENCY_TIER_MID_RATE = 0.08
CONTINGENCY_TIER_HIGH_RATE = 0.12

# ─── Training room turnover ───────────────────────────────────────────────────

TRAINING_TURNOVER_BUFFER_MINUTES = 30

# ─── Pagination ───────────────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ─── Roles ────────────────────────────────────────────────────────────────────

ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_CONSTRUCTION_MANAGER = "ConstructionManager"
ROLE_LICENSING_COORDINATOR = "LicensingCoordinator"
ROLE_SYSTEMS_INTEGRATOR = "SystemsIntegrator"
ROLE_TALENT_MANAGER = "TalentManager"
ROLE_PROCUREMENT_MANAGER = "ProcurementManager"
ROLE_COMMERCIAL_DIRECTOR = "CommercialDirector"
ROLE_QUALITY_INSPECTOR = "QualityInspector"

ALL_ROLES = [
    ROLE_PROGRAM_DIRECTOR,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_LICENSING_COORDINATOR,
    ROLE_SYSTEMS_INTEGRATOR,
    ROLE_TALENT_MANAGER,
    ROLE_PROCUREMENT_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_QUALITY_INSPECTOR,
]

# The five operations refused with ERR_PROGRAM_FROZEN while the posture is FROZEN.
FROZEN_BLOCKED_OPERATIONS = [
    "create-reservation-block",
    "guarantee-block",
    "open-booking",
    "receive-ose-order",
    "authorize-soft-opening",
]
