"""Named constants the PRD fixes for the retail media network API.

Every value here is quoted from the PRD rather than chosen by the test author, so a
test that computes an expected figure reproduces the PRD's arithmetic instead of
hard-coding a magic number.
"""

# --- Routing ---------------------------------------------------------------

API_PREFIX = "/rmn"

# The clock and checkpoint endpoints sit outside the business prefix.
CLOCK_PATH = "/_clock/set_current_utc"
DAILY_CHECKPOINT_PATH = "/_ops/run-daily-checkpoint"


# --- Logical clock ---------------------------------------------------------

# The logical clock reads exactly this instant at every server boot and never
# falls back to wall-clock time.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"


# --- Pagination ------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# --- Relevance score composition ------------------------------------------

SEGMENT_BONUS_NEW = 0.0
SEGMENT_BONUS_RETURNING = 0.03
SEGMENT_BONUS_LOYALTY = 0.06
SEGMENT_BONUS = {
    "NEW": SEGMENT_BONUS_NEW,
    "RETURNING": SEGMENT_BONUS_RETURNING,
    "LOYALTY": SEGMENT_BONUS_LOYALTY,
}

# relevance_score is rounded to four decimals and clamped to [0.0000, 1.0000].
RELEVANCE_SCORE_DECIMALS = 4
RELEVANCE_SCORE_MIN = 0.0
RELEVANCE_SCORE_MAX = 1.0


# --- Line item priority tier ----------------------------------------------

TIER_1_RATIO_MIN = 0.5
TIER_2_RATIO_MIN = 0.2

TIER_MULTIPLIER_TIER_1 = 1.1
TIER_MULTIPLIER_TIER_2 = 1.0
TIER_MULTIPLIER_TIER_3 = 0.9
TIER_MULTIPLIER = {
    "TIER_1": TIER_MULTIPLIER_TIER_1,
    "TIER_2": TIER_MULTIPLIER_TIER_2,
    "TIER_3": TIER_MULTIPLIER_TIER_3,
}

# quality_adjusted_score is rounded to four decimals, round-half-up.
QUALITY_SCORE_DECIMALS = 4


# --- Auction clearing and settlement --------------------------------------

SECOND_PRICE_INCREMENT_CENTS = 1
CPM_DIVISOR = 1000


# --- Attribution ----------------------------------------------------------

MATCH_WEIGHT_CLICK = 1.0
MATCH_WEIGHT_OFFSITE_VIEW = 0.4
MATCH_WEIGHT_IMPRESSION = 0.2
MATCH_WEIGHT = {
    "CLICK": MATCH_WEIGHT_CLICK,
    "OFFSITE_VIEW": MATCH_WEIGHT_OFFSITE_VIEW,
    "IMPRESSION": MATCH_WEIGHT_IMPRESSION,
}
ATTRIBUTION_WEIGHT_DECIMALS = 4


# --- Incrementality -------------------------------------------------------

# A study publishes only when its significance_score reaches this floor.
SIGNIFICANCE_MIN = 1.96
SIGNIFICANCE_DECIMALS = 4

# Minimum clear gap, in days, between two study windows on one campaign.
WASHOUT_DAYS = 7
WASHOUT_HOURS = WASHOUT_DAYS * 24


# --- Off-site reconciliation ----------------------------------------------

# A variance of exactly 2.00 percent selects the logged basis.
VARIANCE_TOLERANCE_PCT = 2.0
VARIANCE_PCT_DECIMALS = 2


# --- Campaign pacing ------------------------------------------------------

PACING_CATCHUP_THRESHOLD = 0.8
PACING_CATCHUP_FACTOR = 1.25
PACING_INDEX_DECIMALS = 4


# --- Slot occupancy -------------------------------------------------------

# Every window comparison is half-open: start inclusive, end exclusive.
OVERLAP_START_INCLUSIVE = True
OVERLAP_END_EXCLUSIVE = True

# Line item statuses that occupy a placement slot.
OCCUPYING_LINE_ITEM_STATUSES = (
    "ELIGIBLE",
    "SERVING",
    "OOS_PAUSED",
    "MANUAL_PAUSED",
)

# Line item statuses excluded from every occupancy rule.
NON_OCCUPYING_LINE_ITEM_STATUSES = (
    "DRAFT",
    "PENDING_ELIGIBILITY",
    "REJECTED",
    "ENDED",
)

MIN_FLIGHT_DAYS = 1


# --- Budget plan and trade fund ------------------------------------------

MIN_TOP_UP_CENTS = 50000
MAX_REVISION_ROUNDS = 3
MIN_ACCRUAL_CENTS = 1000
MIN_APPROVAL_CREDIT_LIMIT_CENTS = 100000

# Campaign delivery statuses that hold a reservation against the plan.
RESERVING_DELIVERY_STATUSES = ("SCHEDULED", "DELIVERING", "PAUSED")

# Campaign delivery statuses that reserve nothing.
NON_RESERVING_DELIVERY_STATUSES = (
    "DRAFT",
    "PENDING_REVIEW",
    "COMPLETED",
    "REJECTED",
    "ARCHIVED",
)


# --- Invoice waterfall ----------------------------------------------------

DEDUCTION_TIER_1_MAX_CENTS = 1000000
DEDUCTION_TIER_2_MAX_CENTS = 5000000
DEDUCTION_TIER_1_PCT = 0.2
DEDUCTION_TIER_2_PCT = 0.35
DEDUCTION_TIER_3_PCT = 0.5

NET_TERMS_DAYS = 30
DISPUTE_GRACE_DAYS = 15
WRITE_OFF_DAYS = 60
MAX_ADJUSTMENT_ROUNDS = 2


# --- Dispute SLA clock ----------------------------------------------------

SLA_BASE_HOURS_IMPRESSION_DISCREPANCY = 72
SLA_BASE_HOURS_ATTRIBUTION_WINDOW = 120
SLA_BASE_HOURS_OFFSITE_SPEND_VARIANCE = 96
SLA_BASE_HOURS_INCREMENTALITY_RESTATEMENT = 240
SLA_BASE_HOURS = {
    "IMPRESSION_DISCREPANCY": SLA_BASE_HOURS_IMPRESSION_DISCREPANCY,
    "ATTRIBUTION_WINDOW": SLA_BASE_HOURS_ATTRIBUTION_WINDOW,
    "OFFSITE_SPEND_VARIANCE": SLA_BASE_HOURS_OFFSITE_SPEND_VARIANCE,
    "INCREMENTALITY_RESTATEMENT": SLA_BASE_HOURS_INCREMENTALITY_RESTATEMENT,
}

SLA_MANAGED_REDUCTION_HOURS = 24
INFO_REQUEST_EXTENSION_HOURS = 48
SLA_FLOOR_HOURS = 24
MAX_INFO_REQUESTS = 2


# --- Dispute credit award -------------------------------------------------

IMPRESSION_EVIDENCE_PCT = 0.25
IROAS_TARGET = 3.0
SLA_BREACH_UPLIFT = 1.1
