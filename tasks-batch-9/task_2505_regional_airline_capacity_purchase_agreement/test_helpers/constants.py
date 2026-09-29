"""Domain constants for the Regional CPA Settlement API.

Every value here is fixed by the PRD prose (never by a test's own arithmetic), so
a test that needs a threshold reads it from this module instead of inlining a
magic number.
"""

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

API_PREFIX = "/cpa"

# The logical clock begins at this fixed instant when the service starts and
# only an administrator can drive it forward.
INITIAL_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_CPA_ADMINISTRATOR = "CPAAdministrator"
ROLE_MAINLINE_SCHEDULER = "MainlineScheduler"
ROLE_REGIONAL_OPS_CONTROLLER = "RegionalOpsController"
ROLE_BASE_CHIEF_PILOT = "BaseChiefPilot"
ROLE_BRAND_AUDITOR = "BrandAuditor"

ALL_ROLES = (
    ROLE_CPA_ADMINISTRATOR,
    ROLE_MAINLINE_SCHEDULER,
    ROLE_REGIONAL_OPS_CONTROLLER,
    ROLE_BASE_CHIEF_PILOT,
    ROLE_BRAND_AUDITOR,
)

# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------

AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "EXTENSION_PENDING", "EXPIRED", "TERMINATED")
AGREEMENT_TERMINAL_STATUSES = ("EXPIRED", "TERMINATED")

CREW_BASE_LIFECYCLE_STATUSES = ("ACTIVE", "CLOSED")
STAFFING_POSTURES = ("STAFFED", "SHORT", "CRITICAL")

AIRCRAFT_STATUSES = (
    "PENDING_INDUCTION",
    "IN_SERVICE",
    "GROUNDED_STAFFING",
    "TRANSITION_PENDING",
    "TRANSITIONED",
    "WITHDRAWN",
)
AIRCRAFT_TERMINAL_STATUSES = ("TRANSITIONED", "WITHDRAWN")
OWNERSHIP_FORMS = ("REGIONAL_OWNED", "MAINLINE_OWNED", "LEASED")
TRANSITION_REASONS = ("FLEET_RENEWAL", "LEASE_EXPIRY", "PARTNER_RECALL")
GROUNDED_REASON_STAFFING_SHORTFALL = "STAFFING_SHORTFALL"

PILOT_STATUSES = (
    "PIPELINE",
    "IN_TRAINING",
    "LINE_QUALIFIED",
    "ATTRITED_TO_MAINLINE",
    "RESIGNED",
)
PILOT_TERMINAL_STATUSES = ("ATTRITED_TO_MAINLINE", "RESIGNED")
PILOT_SEATS = ("CAPTAIN", "FIRST_OFFICER")
ATTRITION_DESTINATIONS = ("MAINLINE", "OTHER")

SCHEDULE_CYCLE_STATUSES = ("PLANNED", "OPEN", "CLOSED", "SETTLED")

FLIGHT_LEG_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
FLIGHT_LEG_TERMINAL_STATUSES = ("COMPLETED",)
CANCEL_CAUSE_CODES = (
    "CREW_UNAVAILABLE",
    "MAINTENANCE",
    "WEATHER",
    "ATC",
    "MAINLINE_REQUEST",
    "SECURITY",
)

CANCELLATION_CLAIM_STATUSES = ("OPEN", "CLASSIFIED", "DISPUTED", "FINALIZED", "VOIDED")
CANCELLATION_CLAIM_TERMINAL_STATUSES = ("FINALIZED", "VOIDED")
CLASSIFICATIONS = ("CONTROLLABLE", "UNCONTROLLABLE")

PASSTHROUGH_CLAIM_STATUSES = ("SUBMITTED", "ACTUAL_SUBMITTED", "RECONCILED", "REJECTED")
PASSTHROUGH_CLAIM_TERMINAL_STATUSES = ("RECONCILED", "REJECTED")
PASSTHROUGH_CATEGORIES = ("FUEL", "AIRPORT_FEES", "INSURANCE")
RECONCILE_DECISIONS = ("APPROVE", "REJECT")

SCORECARD_STATUSES = ("PUBLISHED", "STALE")

INVOICE_STATUSES = ("DRAFT", "ISSUED", "VOIDED")
INVOICE_VARIANTS = ("PROVISIONAL", "FINAL")
VOID_REASONS = ("MANUAL", "AUTO_SCORECARD_STALE", "AUTO_SUPERSEDED")

BRAND_FINDING_STATUSES = ("OPEN", "ACKNOWLEDGED", "CLOSED")
BRAND_REMEDIATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "VERIFIED")
BRAND_AUDIT_SCOPES = ("UNIFORM", "CABIN_PRODUCT", "SERVICE_SCRIPT", "LIVERY")
BRAND_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")

NEGOTIATION_STATUSES = ("OFFERED", "COUNTERED", "ACCEPTED", "WITHDRAWN")
NEGOTIATION_TERMINAL_STATUSES = ("ACCEPTED", "WITHDRAWN")

# ---------------------------------------------------------------------------
# Precision and rounding
# ---------------------------------------------------------------------------

MONEY_PRECISION = 2
BLOCK_HOURS_PRECISION = 3
PERCENT_PRECISION = 2

# Tolerance used when comparing two-decimal money and percentage figures.
MONEY_TOLERANCE = 0.005
# Tolerance used when comparing three-decimal block-hour figures.
BLOCK_HOURS_TOLERANCE = 0.0005

# ---------------------------------------------------------------------------
# Performance scoring
# ---------------------------------------------------------------------------

# An arrival is on time when it is no later than the scheduled arrival plus a
# fourteen-minute grace allowance; the boundary is inclusive.
ON_TIME_GRACE_MINUTES = 14

CF_TIER_HIGH_PCT = 99.00
CF_TIER_MID_PCT = 97.50
CF_POINTS_HIGH = 3
CF_POINTS_MID = 0
CF_POINTS_LOW = -4

OTA_TIER_HIGH_PCT = 85.00
OTA_TIER_MID_PCT = 80.00
OTA_POINTS_HIGH = 2
OTA_POINTS_MID = 0
OTA_POINTS_LOW = -3

BAG_TIER_LOW_PER_1000 = 3.00
BAG_TIER_MID_PER_1000 = 5.50
BAG_POINTS_HIGH = 1
BAG_POINTS_MID = 0
BAG_POINTS_LOW = -2

POINT_VALUE_USD = 12000.00
INCENTIVE_REVENUE_SHARE = 0.05

# Pinned conventions for degenerate denominators.
ZERO_ELIGIBLE_RESULT_PCT = 100.00
EMPTY_SET_RESULT_PCT = 100.00
ZERO_BAGS_RESULT = 0.00

# ---------------------------------------------------------------------------
# Brand standards
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT_USD = {
    "MINOR": 500.00,
    "MAJOR": 2500.00,
    "CRITICAL": 7500.00,
}
BRAND_PENALTY_CAP_USD = 25000.00

# ---------------------------------------------------------------------------
# Pass-through reconciliation waterfall
# ---------------------------------------------------------------------------

# FUEL is passed through uncapped; the other two categories are capped at a
# tolerance above the accrual.
CATEGORY_TOLERANCE = {
    "FUEL": None,
    "AIRPORT_FEES": 0.10,
    "INSURANCE": 0.05,
}

ADMIN_TIER_1_USD = 100000.00
ADMIN_TIER_2_USD = 500000.00
ADMIN_FEE_TIER_LOW_RATE = 0.030
ADMIN_FEE_TIER_MID_RATE = 0.020
ADMIN_FEE_TIER_HIGH_RATE = 0.015

# ---------------------------------------------------------------------------
# Crewing arithmetic
# ---------------------------------------------------------------------------

# Each pilot in training counts as sixty-five hundredths of a line pilot;
# thirty-five hundredths of the pipeline is discounted for expected attrition.
ATTRITION_DISCOUNT = 0.35
PIPELINE_CREDIT = 0.65

# ---------------------------------------------------------------------------
# Temporal capacity rules
# ---------------------------------------------------------------------------

AIRCRAFT_MIN_TURN_MINUTES = 35
PILOT_ROLLING_BLOCK_CAP_HOURS = 16.000
PILOT_DUTY_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Bargaining loop bounds
# ---------------------------------------------------------------------------

MAX_DISPUTE_ROUNDS = 2
MAX_COUNTER_ROUNDS = 2

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100
