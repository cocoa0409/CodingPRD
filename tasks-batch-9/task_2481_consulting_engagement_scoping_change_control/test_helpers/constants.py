"""Domain constants for the Consulting Engagement Scoping & Change Control API.

Every value here is transcribed from PRD.md. Nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Mounting and pagination (PRD 1, 2.3)
# ---------------------------------------------------------------------------

API_PREFIX = "/consulting"

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_ENGAGEMENT_PARTNER = "EngagementPartner"
ROLE_ENGAGEMENT_MANAGER = "EngagementManager"
ROLE_QUALITY_REVIEWER = "QualityReviewer"
ROLE_FIRM_LEADERSHIP = "FirmLeadership"
ROLE_CLIENT_CONTACT = "ClientContact"
ROLE_PRACTICE_ADMIN = "PracticeAdmin"

ALL_ROLES = (
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QUALITY_REVIEWER,
    ROLE_FIRM_LEADERSHIP,
    ROLE_CLIENT_CONTACT,
    ROLE_PRACTICE_ADMIN,
)

# ---------------------------------------------------------------------------
# Audit properties (PRD 2.4)
# ---------------------------------------------------------------------------

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
# SatisfactionAssessment is the single exception: only id and created_at.
SATISFACTION_AUDIT_FIELDS = ("id", "created_at")
SATISFACTION_ABSENT_FIELDS = ("updated_at", "version")

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.6)
# ---------------------------------------------------------------------------

CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Money and the rate card (PRD 2.8)
# ---------------------------------------------------------------------------

GRADE_PARTNER = "PARTNER"
GRADE_MANAGER = "MANAGER"
GRADE_CONSULTANT = "CONSULTANT"
GRADE_ANALYST = "ANALYST"
GRADES = (GRADE_PARTNER, GRADE_MANAGER, GRADE_CONSULTANT, GRADE_ANALYST)

BILLING_RATE_CENTS_PER_HOUR = {
    GRADE_PARTNER: 92500,
    GRADE_MANAGER: 57500,
    GRADE_CONSULTANT: 36500,
    GRADE_ANALYST: 21500,
}

BLENDED_FORECAST_RATE_CENTS_PER_HOUR = 34000

# ---------------------------------------------------------------------------
# Master data enumerations (PRD 3.1)
# ---------------------------------------------------------------------------

INDUSTRY_CODES = ("RETAIL", "INDUSTRIAL", "FINSVC", "PUBLIC", "HEALTH")
DECISION_PROCESSES = ("SINGLE_APPROVER", "COMMITTEE", "PROCUREMENT_LED")
PRACTICE_CODES = ("OPS", "STRATEGY", "DIGITAL", "RISK")

CLIENT_STATUS_ACTIVE = "ACTIVE"
CLIENT_STATUS_CREDIT_HOLD = "CREDIT_HOLD"
CLIENT_STATUS_INACTIVE = "INACTIVE"

# ---------------------------------------------------------------------------
# Qualification scoring (PRD 3.2)
# ---------------------------------------------------------------------------

DECISION_PROCESS_FACTOR = {
    "SINGLE_APPROVER": 1.0,
    "COMMITTEE": 0.8,
    "PROCUREMENT_LED": 0.6,
}
QUALIFICATION_THRESHOLD = 60.00

CONFLICT_NOT_CHECKED = "NOT_CHECKED"
CONFLICT_CLEAR = "CLEAR"
CONFLICT_CLEARED_WITH_WAIVER = "CLEARED_WITH_WAIVER"
CONFLICT_WAIVER_REQUIRED = "WAIVER_REQUIRED"
CONFLICT_BLOCKED = "BLOCKED"

OPPORTUNITY_STATUSES = (
    "SCREENING",
    "QUALIFIED",
    "SCOPING",
    "SCOPE_BASELINED",
    "SOW_ISSUED",
    "WON",
    "LOST",
    "DISQUALIFIED",
)

# ---------------------------------------------------------------------------
# Baselining (PRD 3.4)
# ---------------------------------------------------------------------------

SCOPE_DISCOUNT_TIER_NONE = 0.00
SCOPE_DISCOUNT_TIER_MID = 0.05
SCOPE_DISCOUNT_TIER_HIGH = 0.10
SCOPE_DISCOUNT_MID_FLOOR_HOURS = 200
SCOPE_DISCOUNT_HIGH_FLOOR_HOURS = 500

# ---------------------------------------------------------------------------
# Statement of work (PRD 3.5)
# ---------------------------------------------------------------------------

PRICING_FIXED_FEE = "FIXED_FEE"
PRICING_TIME_AND_MATERIALS = "TIME_AND_MATERIALS"
PRICING_OUTCOME_BASED = "OUTCOME_BASED"

RISK_POINTS_PRICING = {
    PRICING_FIXED_FEE: 25,
    PRICING_TIME_AND_MATERIALS: 10,
    PRICING_OUTCOME_BASED: 40,
}
RISK_POINTS_DECISION = {
    "SINGLE_APPROVER": 5,
    "COMMITTEE": 15,
    "PROCUREMENT_LED": 20,
}
RISK_SPECIFICATION_BASE_POINTS = 20
RISK_SPECIFICATION_POINTS_PER_STATEMENT = 4
RISK_DEPENDENCY_POINTS_PER_NODE = 5
RISK_DEPENDENCY_CAP = 15
RISK_OBLIGATION_POINTS_PER_ENTRY = 3
RISK_OBLIGATION_CAP = 15
RISK_SCORE_CAP = 100

RISK_TIER_MEDIUM_FLOOR = 30
RISK_TIER_HIGH_FLOOR = 60
RISK_PREMIUM_LOW = 0.05
RISK_PREMIUM_MEDIUM = 0.12
RISK_PREMIUM_HIGH = 0.20

NTE_MULTIPLIER_LOW = 1.05
NTE_MULTIPLIER_MEDIUM = 1.10
NTE_MULTIPLIER_HIGH = 1.15

OUTCOME_FIXED_SHARE = 0.70
OUTCOME_AT_RISK_CAP_SHARE = 0.35
OUTCOME_BENEFIT_SHARE_CAP = 0.20

REVISION_ROUND_LIMIT = 3

SOW_STATUSES = (
    "DRAFT",
    "INTERNAL_REVIEW",
    "CLIENT_REVIEW",
    "REVISION_REQUESTED",
    "SIGNED",
    "DECLINED",
    "SUPERSEDED",
)

# ---------------------------------------------------------------------------
# Engagement and delivery (PRD 3.6)
# ---------------------------------------------------------------------------

DELIVERY_MOBILIZING = "MOBILIZING"
DELIVERY_ACTIVE = "ACTIVE"
DELIVERY_ON_HOLD = "ON_HOLD"
DELIVERY_CLOSING = "CLOSING"
DELIVERY_CLOSED = "CLOSED"

ECONOMICS_ON_TRACK = "ON_TRACK"
ECONOMICS_AT_RISK = "AT_RISK"
ECONOMICS_OVERRUN = "OVERRUN"

DELIVERABLE_PLANNED = "PLANNED"
DELIVERABLE_IN_PROGRESS = "IN_PROGRESS"
DELIVERABLE_SUBMITTED = "SUBMITTED"
DELIVERABLE_ACCEPTED = "ACCEPTED"
DELIVERABLE_REWORK = "REWORK"
DELIVERABLE_SUSPENDED = "SUSPENDED"

MAX_EFFORT_HOURS_ESTIMATE = 5000.00
MAX_COMPLETION_WEIGHT_PCT = 100.00
COMPLETION_WEIGHT_SUM_REQUIRED = 100.00

CAPACITY_OVERLAP_REFUSAL_COUNT = 2

# ---------------------------------------------------------------------------
# Timesheets and economics (PRD 3.7)
# ---------------------------------------------------------------------------

TIMESHEET_HOURS_MIN_EXCLUSIVE = 0.00
TIMESHEET_HOURS_MAX = 60.00

TIME_ENTRY_SUBMITTED = "SUBMITTED"
TIME_ENTRY_APPROVED = "APPROVED"
TIME_ENTRY_REJECTED = "REJECTED"
TIME_ENTRY_REVERSED = "REVERSED"

ECONOMICS_VIEW_FIELDS = (
    "hours_burn_pct",
    "completion_pct",
    "progress_variance_pct",
    "projected_cost_cents",
    "projected_margin_pct",
    "economics_state",
)

OVERRUN_VARIANCE_FLOOR = 30.00
OVERRUN_MARGIN_CEILING = 0.00
AT_RISK_VARIANCE_FLOOR = 15.00
AT_RISK_MARGIN_CEILING = 15.00

# ---------------------------------------------------------------------------
# Change control (PRD 3.8)
# ---------------------------------------------------------------------------

CHANGE_ORIGIN_CLIENT_REQUEST = "CLIENT_REQUEST"
CHANGE_ORIGIN_DELIVERY_TEAM = "DELIVERY_TEAM"

CR_DRAFT = "DRAFT"
CR_IMPACT_ASSESSED = "IMPACT_ASSESSED"
CR_PENDING_LEADERSHIP_APPROVAL = "PENDING_LEADERSHIP_APPROVAL"
CR_PENDING_CLIENT_APPROVAL = "PENDING_CLIENT_APPROVAL"
CR_APPROVED = "APPROVED"
CR_REJECTED = "REJECTED"
CR_RESCINDED = "RESCINDED"

ROUTING_LEADERSHIP_THEN_CLIENT = "LEADERSHIP_THEN_CLIENT"
ROUTING_CLIENT_ONLY = "CLIENT_ONLY"

MATERIALITY_CEILING_PCT = 40.00
LEADERSHIP_ROUTING_FLOOR_PCT = 20.00
MAX_REQUESTED_SCHEDULE_DAYS = 180
MAX_ADDED_HOURS = 5000.00

# ---------------------------------------------------------------------------
# Quality, escalation, closure and satisfaction (PRD 3.9)
# ---------------------------------------------------------------------------

CHECKPOINT_SCOPE_GATE = "SCOPE_GATE"
CHECKPOINT_MIDPOINT = "MIDPOINT"
CHECKPOINT_PRE_DELIVERY = "PRE_DELIVERY"
CHECKPOINT_TYPES = (CHECKPOINT_SCOPE_GATE, CHECKPOINT_MIDPOINT, CHECKPOINT_PRE_DELIVERY)

REVIEW_SCHEDULED = "SCHEDULED"
REVIEW_PASSED = "PASSED"
REVIEW_CONDITIONAL = "CONDITIONAL"
REVIEW_FAILED = "FAILED"

SEVERITY_NONE = "NONE"
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"

REVIEW_WINDOW_MIN_GAP_DAYS = 3

ESCALATION_SOURCE_QUALITY = "QUALITY"
ESCALATION_SOURCE_ECONOMICS = "ECONOMICS"

ESCALATION_OPEN = "OPEN"
ESCALATION_ACKNOWLEDGED = "ACKNOWLEDGED"
ESCALATION_DELIVERY_HELD = "DELIVERY_HELD"
ESCALATION_RESOLVED = "RESOLVED"

RESPONSE_ACKNOWLEDGE = "ACKNOWLEDGE"
RESPONSE_HOLD_DELIVERY = "HOLD_DELIVERY"
RESPONSE_RESOLVE = "RESOLVE"

CSAT_WEIGHT_DELIVERY = 0.40
CSAT_WEIGHT_VALUE = 0.35
CSAT_WEIGHT_COMMUNICATION = 0.25
CSAT_REFERRAL_BONUS = 0.25
CSAT_MAX = 10.00
FOLLOW_ON_CSAT_FLOOR = 7.50

# ---------------------------------------------------------------------------
# Fixture seed data (shared across the suite)
# ---------------------------------------------------------------------------

SEED_CLOCK = "2026-08-03T09:00:00Z"
# Delivery-phase instants, both later than SEED_CLOCK so the clock stays
# forward-only (PRD 2.6).
SEED_DELIVERY_CLOCK = "2026-09-14T09:00:00Z"
SEED_REVIEW_CLOCK = "2026-09-22T09:00:00Z"
SEED_WEEK_1 = "2026-09-04"
SEED_WEEK_2 = "2026-09-11"

SEED_CLIENT_NAME = "Northwind Retail Group"
SEED_CLIENT_CODE = "NWR001"
SEED_CLIENT_INDUSTRY = "RETAIL"
SEED_CLIENT_DECISION_PROCESS = "COMMITTEE"
SEED_CLIENT_BUDGET_AUTHORITY_CENTS = 80000000
SEED_CLIENT_ADVERSE_PARTY_CODES = ["ACMECORP"]
SEED_UNRELATED_ADVERSE_PARTY_CODES = ["GLOBEXLTD"]

SEED_PRACTICE_CODE = "OPS"
SEED_PARTNER_COST_RATE = 62000
SEED_MANAGER_COST_RATE = 38000
SEED_CONSULTANT_COST_RATE = 24000
SEED_REVIEWER_COST_RATE = 40000
SEED_LEADERSHIP_COST_RATE = 70000

SEED_ESTIMATED_VALUE_CENTS = 100000000
SEED_STATED_BUDGET_CENTS = 60000000
SEED_VERIFIED_BUDGET_CENTS = 60000000
SEED_TARGET_START_DATE = "2026-09-01"
SEED_TARGET_END_DATE = "2026-12-18"
SEED_OBJECTIVE_SUMMARY = "Redesign the national distribution network"

SEED_ASSUMPTIONS = [
    "Client master data is available by week 2",
    "No works-council consultation is required",
]
SEED_EXCLUSIONS = ["Systems implementation"]
SEED_CLIENT_RESPONSIBILITIES = ["Weekly steering committee attendance"]

SEED_ACCEPTANCE_SUMMARY = (
    "Written client sign-off per deliverable within 10 business days"
)
SEED_SIGNATURE_NAME = "R. Vance"

# The canonical two-deliverable scope: 120.25h CONSULTANT + 80.50h MANAGER.
SEED_D1 = {
    "name": "Current-state diagnostic",
    "primary_grade": GRADE_CONSULTANT,
    "effort_hours_estimate": 120.25,
    "completion_weight_pct": 40.0,
    "acceptance_criteria": "Signed-off baseline cost-to-serve model",
    "planned_start_date": "2026-09-01",
    "planned_end_date": "2026-10-15",
}
SEED_D2 = {
    "name": "Target-state network design",
    "primary_grade": GRADE_MANAGER,
    "effort_hours_estimate": 80.5,
    "completion_weight_pct": 60.0,
    "acceptance_criteria": "Approved design pack with transition plan",
    "planned_start_date": "2026-10-16",
    "planned_end_date": "2026-12-18",
}

# Derived figures of the canonical scope, worked by hand from PRD 3.4 / 3.5.
CANON_TOTAL_ESTIMATED_HOURS = 200.75
CANON_SCOPE_DISCOUNT_PCT = 0.05
CANON_D1_LINE_COST_CENTS = 4169669
CANON_D2_LINE_COST_CENTS = 4397313
CANON_BASELINE_EFFORT_COST_CENTS = 8566982
CANON_LONGEST_DEPENDENCY_CHAIN = 2

CANON_FIXED_FEE_RISK_SCORE = 61
CANON_FIXED_FEE_QUOTED_CENTS = 10280378
CANON_TNM_RISK_SCORE = 46
CANON_TNM_QUOTED_CENTS = 9423680

NON_EXISTENT_ID = "00000000-0000-0000-0000-0000000000ff"
