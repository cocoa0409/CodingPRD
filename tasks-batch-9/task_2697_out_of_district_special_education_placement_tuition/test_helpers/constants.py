"""
Business constants for the Out-of-District Special Education Placement & Tuition API.

Every value here is quoted from the PRD. Tests reference these names instead of
repeating magic numbers so that a reader can see which declared constant a
computation depends on.
"""

# ─── Logical clock ────────────────────────────────────────────────────────────
# The clock reads exactly this instant before any client sets it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_SET_PATH = "/_clock/set_current_utc"

# ─── Mount point ──────────────────────────────────────────────────────────────
MOUNT = "/ood-placements"

# ─── Pagination ───────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Roles ────────────────────────────────────────────────────────────────────
ROLE_PLACEMENT_COORDINATOR = "PlacementCoordinator"
ROLE_TEAM_CHAIR = "TeamChair"
ROLE_FISCAL_OFFICER = "FiscalOfficer"
ROLE_SCHOOL_BILLING_AGENT = "SchoolBillingAgent"
ROLE_PARENT_GUARDIAN = "ParentGuardian"
ROLE_HEARING_ADJUDICATOR = "HearingAdjudicator"
ROLE_SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = [
    ROLE_PLACEMENT_COORDINATOR,
    ROLE_TEAM_CHAIR,
    ROLE_FISCAL_OFFICER,
    ROLE_SCHOOL_BILLING_AGENT,
    ROLE_PARENT_GUARDIAN,
    ROLE_HEARING_ADJUDICATOR,
    ROLE_SYSTEM_ADMIN,
]

# ─── Transport ────────────────────────────────────────────────────────────────
TRANSPORT_FUEL_INDEX = 1.0325
TURNAROUND_BUFFER_MIN = 10

# ─── Attendance and service delivery ──────────────────────────────────────────
ABSENCE_TOLERANCE_DAYS = 3
SERVICE_PERIOD_WEEKS = 4
SERVICE_TRAVEL_DIFFERENTIAL = 1.075
BILLING_CYCLE_DAYS = 28
BILLING_PERIODS_PER_YEAR = 13

# ─── Invoice pricing ──────────────────────────────────────────────────────────
VARIANCE_TOLERANCE_PCT = 0.02
VOLUME_TIER_1_FLOOR_CENTS = 700000
VOLUME_TIER_2_FLOOR_CENTS = 1000000
VOLUME_TIER_1_RATE = 0.015
VOLUME_TIER_2_RATE = 0.03
ADMIN_FEE_PCT = 0.0225

# ─── Progress reports and return readiness ────────────────────────────────────
W_GOAL = 0.5
W_BENCH = 0.3
W_ATT = 0.2
REGRESSION_PENALTY_POINTS = 4
DECAY_BASE = 0.7
RETURN_READINESS_MIN = 62.50
MIN_ACCEPTED_REPORTS = 2
TRANSITION_SERVICES_RESERVE_CENTS = 250000

# ─── Reimbursement claims ─────────────────────────────────────────────────────
STATE_CAP_DAY_RATE_CENTS = 28000
TRANSPORT_CAP_CENTS = 150000
NOTICE_DAYS_REQUIRED = 10
LATE_NOTICE_REDUCTION_PCT = 0.25
NONCOOPERATION_REDUCTION_PCT = 0.20
TIMELY_OFFER_REDUCTION_PCT = 0.15
MAX_EQUITABLE_REDUCTION_PCT = 0.50

# ─── State high-cost fund and Medicaid ────────────────────────────────────────
HIGH_COST_TRIGGER_CENTS = 4000000
HIGH_COST_TIER_2_FLOOR_CENTS = 2000000
HIGH_COST_TIER_3_FLOOR_CENTS = 6000000
HIGH_COST_TIER_1_RATE = 0.60
HIGH_COST_TIER_2_RATE = 0.75
HIGH_COST_TIER_3_RATE = 0.90
HIGH_COST_MAX_PER_STUDENT_CENTS = 5000000
MEDICAID_HOURLY_RATE_CENTS = 9000
FMAP_PCT = 0.5432

# ─── Placement lifecycle ──────────────────────────────────────────────────────
CONTRACT_ACTIVATION_GRACE_DAYS = 30
MIN_CONTINUUM_OPTIONS = 3
MAX_REVISION_ROUNDS = 3
MAX_AMENDMENT_ROUNDS = 2
MAX_RESUBMISSION_ROUNDS = 2
MAX_REMAND_ROUNDS = 2

# ─── Enumerations ─────────────────────────────────────────────────────────────
PLACEMENT_TYPES = ["DAY", "RESIDENTIAL"]
APPROVAL_STATUSES = ["APPROVED", "PROVISIONAL", "REVOKED"]
RATE_APPROVAL_STATES = ["DRAFT", "STATE_APPROVED", "SUPERSEDED"]
DECISION_STATUSES = [
    "DRAFT",
    "TEAM_REVIEW",
    "RETURNED_FOR_REVISION",
    "APPROVED",
]
PLACEMENT_STATUSES = [
    "PROPOSED",
    "CONTRACTED",
    "ACTIVE",
    "TERMINATED",
    "RETURNED_TO_DISTRICT",
    "EXPIRED",
]
TRANSPORT_STATUSES = [
    "NOT_REQUIRED",
    "PENDING",
    "ASSIGNED",
    "WAITLISTED",
    "RELEASED",
]
ADDENDUM_STATUSES = ["PROPOSED", "ACTIVE", "TERMINATED", "TRANSFERRED"]
ASSIGNMENT_STATUSES = ["REQUESTED", "ACTIVE", "WAITLISTED", "RELEASED"]
ATTENDANCE_STATUSES = ["SUBMITTED", "VERIFIED", "DISPUTED"]
INVOICE_VERIFICATION_STATUSES = ["SUBMITTED", "VERIFIED", "DISPUTED"]
INVOICE_PAYMENT_STATUSES = ["UNPAID", "PAID", "VOIDED"]
CLAIM_STATUSES = [
    "FILED",
    "AWARDED_FULL",
    "AWARDED_PARTIAL",
    "DENIED",
    "REMANDED",
]
AWARD_BASES = ["strict_statutory", "equitable_actual_cost"]
PROGRESS_STATUSES = ["SUBMITTED", "ACCEPTED", "REJECTED"]
PLAN_STATUSES = ["DRAFT", "ACTIVE", "COMPLETED", "ABANDONED"]
FUNDING_CLAIM_TYPES = ["HIGH_COST_FUND", "MEDICAID"]
FUNDING_CLAIM_SOURCES = ["MANUAL", "AUTO_CASCADE"]
FUNDING_CLAIM_STATUSES = ["ELIGIBLE", "SUBMITTED", "PAID", "REJECTED"]
READINESS_VARIANTS = ["trailing_two_quarter", "cumulative_recency_weighted"]
COST_PROJECTION_VARIANTS = ["CONTRACTED_ENCUMBRANCE", "ACTUAL_RUN_RATE"]
SERVICE_TYPES = ["SPEECH", "OT", "PT", "COUNSELING", "BCBA"]
DISABILITY_CATEGORIES = [
    "AUTISM",
    "EMOTIONAL_DISABILITY",
    "INTELLECTUAL_DISABILITY",
    "MULTIPLE_DISABILITIES",
    "SPECIFIC_LEARNING_DISABILITY",
    "OTHER_HEALTH_IMPAIRMENT",
]
LRE_SETTINGS = [
    "GENERAL_ED_80_PLUS",
    "RESOURCE_40_79",
    "SEPARATE_CLASS_UNDER_40",
    "SEPARATE_DAY_SCHOOL",
    "RESIDENTIAL_FACILITY",
]
STUDENT_PLACEMENT_STATUSES = [
    "NONE",
    "DECISION_APPROVED",
    "OOD_ACTIVE",
    "RETURNED",
    "TERMINATED",
]
