"""Domain vocabulary and numeric constants transcribed from the PRD.

Every literal here is quoted from the PRD rather than invented: the role names
of §2.1, the enum members of §3, the thresholds of §2.9's validation ladder and
the weights of the health, load and credit formulas. Tests import the names so
that a typo in an enum member is a Python error rather than a silent mismatch.
"""

# ---------------------------------------------------------------------------
# Paths that are not simple resource routes (PRD §4)
# ---------------------------------------------------------------------------

CLOCK_PATH = "/_clock/set_current_utc"
DAILY_SWEEP_PATH = "/_ops/daily-sweep"

# PRD §2.5: "Until the clock has been set at least once, its value is
# `2026-08-01T00:00:00Z`."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

ROLE_CSM_USER = "CsmUser"
ROLE_CS_OPS_ADMIN = "CsOpsAdmin"
ROLE_CS_EXECUTIVE = "CsExecutive"
ROLE_FINANCE_ANALYST = "FinanceAnalyst"
ROLE_SALES_ACCOUNT_EXECUTIVE = "SalesAccountExecutive"
ROLE_ADVOCACY_MANAGER = "AdvocacyManager"

ALL_ROLES = (
    ROLE_CSM_USER,
    ROLE_CS_OPS_ADMIN,
    ROLE_CS_EXECUTIVE,
    ROLE_FINANCE_ANALYST,
    ROLE_SALES_ACCOUNT_EXECUTIVE,
    ROLE_ADVOCACY_MANAGER,
)

# ---------------------------------------------------------------------------
# Account (PRD §3.1, §3.9)
# ---------------------------------------------------------------------------

LIFECYCLE_ONBOARDING = "ONBOARDING"
LIFECYCLE_ADOPTING = "ADOPTING"
LIFECYCLE_STEADY = "STEADY"
LIFECYCLE_AT_RISK = "AT_RISK"
LIFECYCLE_RENEWED = "RENEWED"
LIFECYCLE_CHURNED = "CHURNED"
LIFECYCLE_WIN_BACK_TARGETED = "WIN_BACK_TARGETED"
LIFECYCLE_ARCHIVED = "ARCHIVED"

SEGMENT_ENTERPRISE = "ENTERPRISE"
SEGMENT_MIDMARKET = "MIDMARKET"
SEGMENT_SMB = "SMB"

TIER_UNASSIGNED = "UNASSIGNED"
TIER_HIGH_TOUCH = "HIGH_TOUCH"
TIER_LOW_TOUCH = "LOW_TOUCH"
TIER_DIGITAL = "DIGITAL"

POSTURE_OPEN = "OPEN"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_FROZEN = "FROZEN"

HEALTH_RED = "RED"
HEALTH_AMBER = "AMBER"
HEALTH_GREEN = "GREEN"

LIKELIHOOD_COMMIT = "COMMIT"
LIKELIHOOD_UPSIDE = "UPSIDE"
LIKELIHOOD_AT_RISK = "AT_RISK"
LIKELIHOOD_OMIT = "OMIT"

CHURN_PRODUCT_GAP = "PRODUCT_GAP"
CHURN_PRICE = "PRICE"
CHURN_SPONSOR_CHURN = "SPONSOR_CHURN"
CHURN_POOR_ONBOARDING = "POOR_ONBOARDING"
CHURN_SUPPORT_QUALITY = "SUPPORT_QUALITY"
CHURN_MERGER_ACQUISITION = "MERGER_ACQUISITION"

LIFECYCLE_ACTION_RENEW = "RENEW"
LIFECYCLE_ACTION_CHURN = "CHURN"
LIFECYCLE_ACTION_WIN_BACK_TARGET = "WIN_BACK_TARGET"
LIFECYCLE_ACTION_REACTIVATE = "REACTIVATE"
LIFECYCLE_ACTION_ARCHIVE = "ARCHIVE"
LIFECYCLE_ACTION_WAIVE_TTV_BREACH = "WAIVE_TTV_BREACH"

# PRD §3.1: "an `ENTERPRISE` account may support 6 reference calls per advocacy
# enrollment, a `MIDMARKET` account 4, and an `SMB` account 2."
REFERENCE_CALLS_CAP_BY_BAND = {
    SEGMENT_ENTERPRISE: 6,
    SEGMENT_MIDMARKET: 4,
    SEGMENT_SMB: 2,
}

# PRD §3.1: "90 days for `ENTERPRISE`, 60 days for `MIDMARKET`, 30 days for `SMB`."
TTV_TARGET_DAYS_BY_BAND = {
    SEGMENT_ENTERPRISE: 90,
    SEGMENT_MIDMARKET: 60,
    SEGMENT_SMB: 30,
}

# ---------------------------------------------------------------------------
# CSM roster and coverage (PRD §3.4)
# ---------------------------------------------------------------------------

CSM_ACTIVE = "ACTIVE"
CSM_ON_LEAVE = "ON_LEAVE"
CSM_OFFBOARDED = "OFFBOARDED"

ASSIGNMENT_QUEUED = "QUEUED"
ASSIGNMENT_COMMITTED = "COMMITTED"
ASSIGNMENT_RELEASED = "RELEASED"
ASSIGNMENT_PREEMPTED = "PREEMPTED"

# PRD §3.4: "9 units for `HIGH_TOUCH`, 5 for `LOW_TOUCH`, 2 for `DIGITAL`."
LOAD_BASE_BY_TIER = {TIER_HIGH_TOUCH: 9, TIER_LOW_TOUCH: 5, TIER_DIGITAL: 2}
# PRD §3.4: "a segment multiplier of 1.50 for `ENTERPRISE`, 1.00 for `MIDMARKET`
# or 0.50 for `SMB`".
LOAD_SEGMENT_MULTIPLIER = {
    SEGMENT_ENTERPRISE: 1.50,
    SEGMENT_MIDMARKET: 1.00,
    SEGMENT_SMB: 0.50,
}
# PRD §3.4: "a risk multiplier of 1.25 when `health_tier` is `RED`, 1.10 when
# `AMBER` and 1.00 when `GREEN`".
LOAD_RISK_MULTIPLIER = {HEALTH_RED: 1.25, HEALTH_AMBER: 1.10, HEALTH_GREEN: 1.00}

# PRD §3.4: "an integer revenue surcharge is added: 4 units when `arr_cents` is
# at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1
# when it is at least 5,000,000, otherwise 0."
LOAD_ARR_SURCHARGE_TIERS = (
    (100_000_000, 4),
    (25_000_000, 2),
    (5_000_000, 1),
)

LOAD_UNITS_MIN = 1
LOAD_UNITS_MAX = 20

# PRD §3.4: revenue floors for the HIGH_TOUCH and LOW_TOUCH segmentation clauses.
SEGMENTATION_HIGH_TOUCH_ARR_FLOOR = 25_000_000
SEGMENTATION_LOW_TOUCH_ARR_FLOOR = 5_000_000

# ---------------------------------------------------------------------------
# Signals and the health model (PRD §3.2)
# ---------------------------------------------------------------------------

SIGNAL_USAGE_PERIOD = "USAGE_PERIOD"
SIGNAL_SUPPORT_TICKET = "SUPPORT_TICKET"

SEVERITY_S1 = "S1"
SEVERITY_S2 = "S2"
SEVERITY_S3 = "S3"
SEVERITY_S4 = "S4"

# PRD §3.2: "12 points for `S1`, 7 for `S2`, 3 for `S3` and 1 for `S4`".
PENALTY_POINTS_BY_SEVERITY = {
    SEVERITY_S1: 12,
    SEVERITY_S2: 7,
    SEVERITY_S3: 3,
    SEVERITY_S4: 1,
}
SLA_BREACH_PENALTY_POINTS = 5
LOW_CSAT_PENALTY_POINTS = 4

USAGE_UTILISATION_WEIGHT = 0.60
USAGE_DEPTH_WEIGHT = 0.40

ADOPTION_WEIGHTS = (0.50, 0.30, 0.20)
ADOPTION_WINDOW_ROWS = 3

SUPPORT_WINDOW_DAYS = 90
SUPPORT_PENALTY_CAP = 45.00
SUPPORT_COMPONENT_MAX = 100.00

HEALTH_WEIGHT_ADOPTION = 0.35
HEALTH_WEIGHT_SUPPORT = 0.25
HEALTH_WEIGHT_EXEC = 0.15
HEALTH_WEIGHT_OUTCOME = 0.25

# PRD §3.2: "the tier is `RED` when `snapshot_health_score` is below 50.00,
# `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at
# least 75.00."
TIER_AMBER_FLOOR = 50.00
TIER_GREEN_FLOOR = 75.00

# PRD §3.1 baseline of a freshly registered account.
BASELINE_ADOPTION_INDEX = 0.00
BASELINE_SUPPORT_RISK_PENALTY = 0.00
BASELINE_EXEC_ENGAGEMENT_SCORE = 25.00
BASELINE_OUTCOME_ATTAINMENT_INDEX = 60.00
BASELINE_HEALTH_SCORE = 43.75

# PRD §3.2: renewal-likelihood thresholds.
LIKELIHOOD_COMMIT_FLOOR = 75.00
LIKELIHOOD_UPSIDE_FLOOR = 60.00
LIKELIHOOD_UPSIDE_DAYS_THRESHOLD = 60

# ---------------------------------------------------------------------------
# Sponsors, engagements and outcome goals (PRD §3.3)
# ---------------------------------------------------------------------------

SPONSOR_ACTIVE = "ACTIVE"
SPONSOR_DEPARTED = "DEPARTED"

SENIORITY_CXO = "CXO"
SENIORITY_VP = "VP"
SENIORITY_DIRECTOR = "DIRECTOR"
SENIORITY_MANAGER = "MANAGER"

ENGAGEMENT_SCHEDULED = "SCHEDULED"
ENGAGEMENT_HELD = "HELD"
ENGAGEMENT_NO_SHOW = "NO_SHOW"
ENGAGEMENT_CANCELLED = "CANCELLED"

ENGAGEMENT_TYPE_QBR = "QBR"
ENGAGEMENT_TYPE_EBR = "EBR"
ENGAGEMENT_TYPE_EXEC_SYNC = "EXEC_SYNC"

OUTCOME_HELD = "HELD"
OUTCOME_NO_SHOW = "NO_SHOW"
OUTCOME_CANCELLED = "CANCELLED"

EXEC_BASE_SCORE = 50.00
EXEC_SENIOR_POINTS = 15.00
EXEC_SENIOR_CAP = 45.00
EXEC_JUNIOR_POINTS = 5.00
EXEC_JUNIOR_CAP = 15.00
EXEC_NO_SHOW_DEBIT = 20.00
EXEC_BUYER_DEBIT = 25.00
EXEC_WINDOW_DAYS = 180
# PRD §3.3: "A 30-minute travel buffer is applied to each existing row's bounds
# on both sides."
ENGAGEMENT_BUFFER_MINUTES = 30

GOAL_DEFINED = "DEFINED"
GOAL_IN_PROGRESS = "IN_PROGRESS"
GOAL_ATTAINED = "ATTAINED"
GOAL_MISSED = "MISSED"
GOAL_WAIVED = "WAIVED"

# PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the
# substitute value 60.00 rather than 0.00".
OUTCOME_EMPTY_SUBSTITUTE = 60.00
# PRD §2.9 rule 28: the weight budget in basis points.
WEIGHT_BUDGET_BP = 10_000
BASIS_POINT_DENOMINATOR = 10_000

# ---------------------------------------------------------------------------
# Save plays and escalations (PRD §3.5)
# ---------------------------------------------------------------------------

PLAY_DRAFT = "DRAFT"
PLAY_ACTIVE = "ACTIVE"
PLAY_SUCCEEDED = "SUCCEEDED"
PLAY_FAILED = "FAILED"
PLAY_ABANDONED = "ABANDONED"

PLAY_ACTION_ACTIVATE = "ACTIVATE"
PLAY_ACTION_SUCCEED = "SUCCEED"
PLAY_ACTION_FAIL = "FAIL"
PLAY_ACTION_ABANDON = "ABANDON"

RISK_ADOPTION_DECLINE = "ADOPTION_DECLINE"
RISK_SUPPORT_ESCALATION = "SUPPORT_ESCALATION"
RISK_SPONSOR_LOSS = "SPONSOR_LOSS"
RISK_OUTCOME_MISS = "OUTCOME_MISS"
RISK_BUDGET_PRESSURE = "BUDGET_PRESSURE"

PLAY_TYPE_EXEC_ALIGNMENT = "EXEC_ALIGNMENT"
PLAY_TYPE_ENABLEMENT_SPRINT = "ENABLEMENT_SPRINT"
PLAY_TYPE_COMMERCIAL_CONCESSION = "COMMERCIAL_CONCESSION"
PLAY_TYPE_TECHNICAL_REMEDIATION = "TECHNICAL_REMEDIATION"

# PRD §3.5: "no calendar day from `window_start_date` through `window_end_date`
# inclusive may already be covered by 2 of the account's plays in state `ACTIVE`."
SAVE_PLAY_DAY_CAPACITY = 2
# PRD §3.5: "subtracts a save-failure penalty of 5.00 from **both**
# `snapshot_health_score` and `trended_health_score`".
SAVE_FAILURE_PENALTY = 5.00
HEALTH_SCORE_FLOOR = 0.00

CASE_OPEN = "OPEN"
CASE_COMMITTED = "COMMITTED"
CASE_DISPUTED = "DISPUTED"
CASE_RESOLVED = "RESOLVED"
CASE_WITHDRAWN = "WITHDRAWN"

CASE_ACTION_COMMIT = "COMMIT"
CASE_ACTION_RESOLVE = "RESOLVE"
CASE_ACTION_WITHDRAW = "WITHDRAW"

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"

# PRD §3.5: "a severity rate of 300 basis points for `CRITICAL`, 150 for `HIGH`
# or 50 for `MEDIUM`".
CREDIT_SEVERITY_RATE_BP = {
    SEVERITY_CRITICAL: 300,
    SEVERITY_HIGH: 150,
    SEVERITY_MEDIUM: 50,
}
# PRD §3.5: "2,000 basis points when it is at least 1,000,000 cents, otherwise
# 1,000 basis points when it is at least 250,000 cents, otherwise none."
CREDIT_DISCOUNT_HIGH_FLOOR_CENTS = 1_000_000
CREDIT_DISCOUNT_HIGH_RATE_BP = 2_000
CREDIT_DISCOUNT_LOW_FLOOR_CENTS = 250_000
CREDIT_DISCOUNT_LOW_RATE_BP = 1_000
# PRD §2.9 rule 29 / §3.5: ten percent of the account's `arr_cents`.
COMMITMENT_CREDIT_CAP_BP = 1_000

COMMITMENT_PROPOSED = "PROPOSED"
COMMITMENT_ACCEPTED = "ACCEPTED"
COMMITMENT_REJECTED = "REJECTED"
COMMITMENT_DELIVERED = "DELIVERED"
COMMITMENT_BREACHED = "BREACHED"
COMMITMENT_WITHDRAWN = "WITHDRAWN"

COMMITMENT_ACTION_ACCEPT = "ACCEPT"
COMMITMENT_ACTION_REJECT = "REJECT"
COMMITMENT_ACTION_DELIVER = "DELIVER"

# ---------------------------------------------------------------------------
# Onboarding milestones (PRD §3.1)
# ---------------------------------------------------------------------------

MILESTONE_PENDING = "PENDING"
MILESTONE_COMPLETED = "COMPLETED"
MILESTONE_OVERDUE = "OVERDUE"
MILESTONE_BLOCKED = "BLOCKED"
MILESTONE_WAIVED = "WAIVED"

MILESTONE_ACTION_COMPLETE = "COMPLETE"
MILESTONE_ACTION_WAIVE = "WAIVE"

CODE_KICKOFF = "KICKOFF"
CODE_DATA_INTEGRATION = "DATA_INTEGRATION"
CODE_FIRST_VALUE = "FIRST_VALUE"
CODE_GO_LIVE = "GO_LIVE"

# ---------------------------------------------------------------------------
# Renewal forecasts (PRD §3.6)
# ---------------------------------------------------------------------------

CS_STATE_DRAFT = "DRAFT"
CS_STATE_SUBMITTED = "SUBMITTED"
CS_STATE_LOCKED = "LOCKED"

FINANCE_STATE_PENDING = "PENDING"
FINANCE_STATE_RECONCILED = "RECONCILED"
FINANCE_STATE_VARIANCE_FLAGGED = "VARIANCE_FLAGGED"

RECONCILE_ACTION_RECONCILE = "RECONCILE"
RECONCILE_ACTION_LOCK = "LOCK"

# PRD §3.6: "0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00
# for `OMIT`".
LIKELIHOOD_WEIGHTS = {
    LIKELIHOOD_COMMIT: 0.95,
    LIKELIHOOD_UPSIDE: 0.70,
    LIKELIHOOD_AT_RISK: 0.35,
    LIKELIHOOD_OMIT: 0.00,
}
# PRD §3.6: "`arr_cents` multiplied by 0.90 for `ENTERPRISE`, 0.80 for
# `MIDMARKET` or 0.65 for `SMB`".
FINANCE_RETENTION_RATE = {
    SEGMENT_ENTERPRISE: 0.90,
    SEGMENT_MIDMARKET: 0.80,
    SEGMENT_SMB: 0.65,
}
# PRD §3.6: "a tolerance of 500 basis points of the CS number".
VARIANCE_TOLERANCE_BP = 500

# ---------------------------------------------------------------------------
# Expansion opportunities (PRD §3.7)
# ---------------------------------------------------------------------------

OPPORTUNITY_IDENTIFIED = "IDENTIFIED"
OPPORTUNITY_HANDED_OFF = "HANDED_OFF"
OPPORTUNITY_ACCEPTED = "ACCEPTED"
OPPORTUNITY_REJECTED = "REJECTED"
OPPORTUNITY_RECYCLED = "RECYCLED"
OPPORTUNITY_EXPIRED = "EXPIRED"

OPPORTUNITY_ACTION_HANDOFF = "HANDOFF"
OPPORTUNITY_ACTION_ACCEPT = "ACCEPT"
OPPORTUNITY_ACTION_REJECT = "REJECT"
OPPORTUNITY_ACTION_RECYCLE = "RECYCLE"

SOURCE_SEAT_SATURATION = "SEAT_SATURATION"
SOURCE_FEATURE_DEPTH = "FEATURE_DEPTH"
SOURCE_EXEC_REQUEST = "EXEC_REQUEST"
SOURCE_OUTCOME_OVERACHIEVEMENT = "OUTCOME_OVERACHIEVEMENT"

# PRD §3.7 qualification-score weights and the normaliser.
QUALIFICATION_WEIGHT_TRENDED = 0.50
QUALIFICATION_WEIGHT_ADOPTION = 0.30
QUALIFICATION_WEIGHT_REVENUE = 0.20
QUALIFICATION_ARR_NORMALISER = 50_000_000
# PRD §2.9 rule 27: "the opportunity's `qualification_score` is at least 65.00."
QUALIFICATION_FLOOR = 65.00
# PRD §3.7: "expires to `EXPIRED` once the logical clock is more than 30 days
# after its `identified_at`".
OPPORTUNITY_STALE_DAYS = 30

# ---------------------------------------------------------------------------
# Advocacy (PRD §3.8)
# ---------------------------------------------------------------------------

ENROLLMENT_NOMINATED = "NOMINATED"
ENROLLMENT_APPROVED = "APPROVED"
ENROLLMENT_ACTIVE = "ACTIVE"
ENROLLMENT_SUSPENDED = "SUSPENDED"
ENROLLMENT_GRADUATED = "GRADUATED"
ENROLLMENT_REVOKED = "REVOKED"

ENROLLMENT_ACTION_APPROVE = "APPROVE"
ENROLLMENT_ACTION_ACTIVATE = "ACTIVATE"
ENROLLMENT_ACTION_SUSPEND = "SUSPEND"
ENROLLMENT_ACTION_LOG_REFERENCE_CALL = "LOG_REFERENCE_CALL"
ENROLLMENT_ACTION_GRADUATE = "GRADUATE"
ENROLLMENT_ACTION_REVOKE = "REVOKE"

PROGRAM_CAB = "CAB"
PROGRAM_REFERENCE = "REFERENCE"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
