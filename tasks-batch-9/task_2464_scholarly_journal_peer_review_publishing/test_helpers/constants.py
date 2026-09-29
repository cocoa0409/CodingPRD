"""Contract constants taken verbatim from the PRD.

Only values the PRD states explicitly live here. Nothing is derived or guessed.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------

# "Before any client sets it, the clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_MS = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Journal configuration defaults (PRD §3.1)
# --------------------------------------------------------------------------

DEFAULT_DOI_PREFIX = "10.5555"
DEFAULT_MIN_COMPLETED_REVIEWS_FOR_DECISION = 2
DEFAULT_MAX_REVISION_ROUNDS = 2
DEFAULT_REVIEW_TARGET_DAYS = 21
DEFAULT_REMINDER_CADENCE_DAYS = 7
DEFAULT_MAX_REMINDERS_PER_INVITATION = 2
DEFAULT_REVIEWER_CONCURRENT_WINDOW_LIMIT = 3
DEFAULT_CONSENSUS_MODE = "UNWEIGHTED"
DEFAULT_MAX_PAGE_COUNT = 30
DEFAULT_MAX_FIGURE_COUNT = 10
DEFAULT_REQUIRES_DATA_AVAILABILITY_STATEMENT = True
DEFAULT_APC_BASE_CENTS = 180000
DEFAULT_PAGE_CHARGE_CENTS_PER_PAGE = 4000
DEFAULT_COLOR_FIGURE_CHARGE_CENTS = 25000
DEFAULT_EMBARGO_MONTHS = 12
DEFAULT_TYPESET_CHANGEOVER_BUFFER_DAYS = 2
DEFAULT_MAX_PROOF_ROUNDS = 2

# --------------------------------------------------------------------------
# Editor / author / reviewer defaults (PRD §3.1)
# --------------------------------------------------------------------------

DEFAULT_EDITOR_STATUS = "ACTIVE"
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 3
DEFAULT_COUNTRY_INCOME_BAND = "HIGH"
DEFAULT_INSTITUTIONAL_AGREEMENT = False
DEFAULT_REVIEWER_STATUS = "ACTIVE"
RELIABILITY_SEED = 50.00

# --------------------------------------------------------------------------
# Integrity screening thresholds (PRD §3.3)
# --------------------------------------------------------------------------

SIMILARITY_BLOCK_THRESHOLD = 40.0
SIMILARITY_FLAG_THRESHOLD = 20.0
MANIPULATED_FIGURE_BLOCK_THRESHOLD = 2
MANIPULATED_FIGURE_FLAG_COUNT = 1

# --------------------------------------------------------------------------
# Reliability scoring (PRD §3.6)
# --------------------------------------------------------------------------

ROLLING_WINDOW_DAYS = 180
DELIVERY_RATE_WEIGHT = 0.45
ON_TIME_RATE_WEIGHT = 0.35
RESPONSIVENESS_RATE_WEIGHT = 0.20
LATENESS_PENALTY_PER_DAY = 2.5
LATENESS_PENALTY_CAP = 20.0
PROBATION_THRESHOLD = 40.00
REINSTATEMENT_THRESHOLD = 60.00
PROBATION_MIN_CLOSED_INVITATIONS = 3
RELIABILITY_WEIGHT_FLOOR = 0.2500

# --------------------------------------------------------------------------
# Consensus banding (PRD §3.7)
# --------------------------------------------------------------------------

RECOMMENDATION_VALUES = {
    "ACCEPT": 4,
    "MINOR_REVISION": 3,
    "MAJOR_REVISION": 2,
    "REJECT": 1,
}
CONSENSUS_ACCEPT_LOWER_BOUND = 3.50
CONSENSUS_MINOR_REVISION_LOWER_BOUND = 2.50
CONSENSUS_MAJOR_REVISION_LOWER_BOUND = 1.75

APPEAL_WINDOW_DAYS = 30

# --------------------------------------------------------------------------
# Fee arithmetic (PRD §3.9)
# --------------------------------------------------------------------------

LICENSE_MULTIPLIERS = {
    "CC_BY": 1.00,
    "CC_BY_NC": 0.90,
    "CC_BY_NC_ND": 0.85,
    "GREEN_SELF_ARCHIVE": 0.00,
}
WAIVER_PCT_BY_INCOME_BAND = {
    "HIGH": 0,
    "UPPER_MIDDLE": 25,
    "LOWER_MIDDLE": 50,
    "LOW": 100,
}
INSTITUTIONAL_AGREEMENT_PCT = 15
MINIMUM_BILLABLE_CENTS = 2000
SURCHARGE_RELIEF_20_FLOOR_CENTS = 250000
SURCHARGE_RELIEF_10_FLOOR_CENTS = 150000

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
