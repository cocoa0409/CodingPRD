"""
Domain constants for the inventory-accuracy / item-level-tagging API.

Every value here is taken from the PRD: the API prefix, the pagination
defaults, the enumerations, the named business constants, and the canonical
worked-example figures the PRD pins in its calculation sections.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
API_PREFIX = "/inventory-integrity"
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Pagination (PRD: default limit 10, limit range 1..100, offset >= 0)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Named business constants
# ---------------------------------------------------------------------------
MAX_REWORK_ROUNDS = 2
MAX_RECOUNT_ROUNDS = 1
MIN_COVERAGE_PCT = 90.00
MIN_ACCELERATED_CADENCE_DAYS = 7
SUPERVISOR_SINGLE_APPROVAL_CAP_CENTS = 500000
PHYSICAL_BLACKOUT_BUFFER_DAYS = 3
NEGATIVE_AUTO_CORRECT_MAX_UNITS = 5
PHANTOM_STALE_DAYS = 45
PHANTOM_MAX_AUTO_UNITS = 3
TAG_PASS_REWARD_BPS = 200
TAG_FAIL_PENALTY_BPS = 1500
VENDOR_SHORTAGE_PENALTY_BPS = 1500

# Authority-threshold ladder constants
STORE_CAP_CENTS = 100000
CATEGORY_FLOOR_CENTS = 5000
MIN_EFFECTIVE_CENTS = 1000
STRICTNESS_THEFT_BPS = 5000
STRICTNESS_VENDOR_SHORTAGE_BPS = 7500
STRICTNESS_DEFAULT_BPS = 10000
REPEAT_PENALTY_PER_POSTED_BPS = 1000
REPEAT_PENALTY_CAP_BPS = 5000

# Tag verification
MIN_READ_RATE_BPS = 9800
SAMPLE_BAND_HIGH_BPS = 9000   # score >= 9000  -> 5 percent
SAMPLE_BAND_MID_BPS = 7500    # score >= 7500  -> 10 percent
SAMPLE_PCT_HIGH = 5
SAMPLE_PCT_MID = 10
SAMPLE_PCT_LOW = 20

# Chargeback tiers (keyed by the GROSS attributable shortage)
TIER_1_CEILING_CENTS = 50000
TIER_2_CEILING_CENTS = 200000
TIER_1_RATE_BPS = 8000
TIER_2_RATE_BPS = 9000
TIER_3_RATE_BPS = 10000
TIER_1_CREDIT_BPS = 1500
TIER_2_CREDIT_BPS = 1000
TIER_3_CREDIT_BPS = 500

# Physical reconciliation waterfall caps, in fixed fill order
PROCESS_ERROR_CAP_BPS = 3000
DAMAGE_CAP_BPS = 2000
THEFT_CAP_BPS = 4000

# Store posture thresholds
SUSPEND_BLOCKED_RATIO_BPS = 2000
SUSPEND_ACCURACY_INDEX_BPS = 9000
PROBATION_RESTRICTED_RATIO_BPS = 3000
PROBATION_ACCURACY_INDEX_BPS = 9500

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
READER_MODES = ("HANDHELD", "OVERHEAD")
READER_MODE_REQUIRED = ("HANDHELD", "OVERHEAD", "EITHER")
READER_CAPABILITIES = ("HANDHELD_ONLY", "OVERHEAD_ONLY", "BOTH")
FULFILLMENT_STATUSES = ("ELIGIBLE", "PROBATION", "SUSPENDED")
CERTIFICATION_LEVELS = ("TIER_1", "TIER_2")
TAG_ENCODING_SCHEMES = ("SGTIN_96", "SGTIN_198", "NONE")
PROMISING_STATES = ("PROMISABLE", "RESTRICTED", "BLOCKED")
TAG_BATCH_STATUSES = (
    "DRAFT",
    "ENCODED",
    "RECEIVED",
    "VERIFIED_PASS",
    "VERIFICATION_FAILED",
    "SCRAPPED",
)
VERIFICATION_OUTCOMES = ("PASS", "FAIL")
COUNT_SCHEDULE_STATUSES = ("ACTIVE", "PAUSED", "RETIRED")
COUNT_TASK_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COUNTED", "RECONCILED", "VOIDED")
INVESTIGATION_STATUSES = (
    "OPEN",
    "IN_REVIEW",
    "CAUSE_PROPOSED",
    "CAUSE_APPROVED",
    "CLOSED",
    "WAIVED",
)
ROOT_CAUSES = ("THEFT", "DAMAGE", "PROCESS_ERROR", "VENDOR_SHORTAGE")
ADJUSTMENT_REASON_CODES = (
    "COUNT_VARIANCE",
    "NEGATIVE_CORRECTION",
    "PHANTOM_CLEAR",
    "PHYSICAL_RECONCILIATION",
)
APPROVAL_STATES = ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED")
POSTING_STATES = ("UNPOSTED", "POSTED", "REVERSED")
SHRINK_PERIOD_STATUSES = ("OPEN", "PROVISIONAL_CLOSED", "FINAL_CLOSED")
PHYSICAL_INVENTORY_STATUSES = (
    "PLANNED",
    "COUNTING",
    "FIRST_PASS_COMPLETE",
    "RECONCILING",
    "CERTIFIED",
    "ABANDONED",
)

# ---------------------------------------------------------------------------
# Canonical reference-data values used by the composite fixtures.
# These are ordinary in-range values; nothing here is a contract statement.
# ---------------------------------------------------------------------------
APPAREL_UPLIFT_BPS = 750
APPAREL_TOLERANCE_UNITS = 2
APPAREL_TOLERANCE_VALUE_CENTS = 20000
APPAREL_MIN_ACCURACY_PCT = 97.00

HOME_UPLIFT_BPS = 0
HOME_TOLERANCE_UNITS = 5
HOME_TOLERANCE_VALUE_CENTS = 6000
HOME_MIN_ACCURACY_PCT = 95.00

ELEC_UPLIFT_BPS = 250
ELEC_TOLERANCE_UNITS = 0
ELEC_TOLERANCE_VALUE_CENTS = 4000
ELEC_MIN_ACCURACY_PCT = 99.00

TEE1_UNIT_COST_CENTS = 1234
TEE2_UNIT_COST_CENTS = 2500
PAN_UNIT_COST_CENTS = 1500
SOFA_UNIT_COST_CENTS = 5000
TV_UNIT_COST_CENTS = 40000

DEFAULT_EPC_PREFIX = "0614141"
DEFAULT_EPC_PREFIX_LENGTH = 7

PERIOD_START = "2026-07-01"
PERIOD_END = "2026-09-30"
PERIOD_SALES_AT_COST_CENTS = 5000000

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-03T00:00:00Z"
