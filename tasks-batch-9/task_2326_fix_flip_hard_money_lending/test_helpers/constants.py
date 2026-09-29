"""Numeric and textual constants declared by the PRD.

Every value here is stated literally in the PRD prose; nothing is inferred.
"""

# ---------------------------------------------------------------- URLs / paths
LENDING = "/lending"
CLOCK_SET_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------- logical clock
# PRD §2.4: "Absent any explicit clock write, the clock reads
# `2026-08-01T00:00:00Z`."
DEFAULT_CURRENT_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- pagination
# PRD §2.3: limit "defaults to 10, has a minimum of 1 and a maximum of 100".
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------- scoring
EXPERIENCE_RECENT_WEIGHT = 40
EXPERIENCE_LIFETIME_WEIGHT = 25
EXPERIENCE_CREDIT_WEIGHT = 20
EXPERIENCE_LIQUIDITY_WEIGHT = 15
RECENT_FLIP_TARGET = 5
LIFETIME_FLIP_TARGET = 10
EXPERIENCE_DEFAULT_PENALTY = 15
LIQUIDITY_COVERAGE_PCT = 0.10
RECERT_LIFETIME_DECAY = 0.5

TIER_A_MIN_SCORE = 80.00
TIER_B_MIN_SCORE = 65.00
TIER_C_MIN_SCORE = 45.00

# PRD §3.3 tier ceiling percentages.
LTP_PCT = {"TIER_A": 0.90, "TIER_B": 0.85, "TIER_C": 0.80, "TIER_D": 0.70}
LTC_PCT = {"TIER_A": 0.90, "TIER_B": 0.85, "TIER_C": 0.80, "TIER_D": 0.70}
LTARV_PCT = {"TIER_A": 0.75, "TIER_B": 0.70, "TIER_C": 0.65, "TIER_D": 0.60}

# ---------------------------------------------------------------- application inputs
MIN_TERM_MONTHS = 6
MAX_TERM_MONTHS = 18
MIN_RATE_BPS = 800
MAX_RATE_BPS = 1800
MIN_INTEREST_RESERVE_MONTHS = 0
MAX_INTEREST_RESERVE_MONTHS = 12
DEFAULT_DAY_COUNT_CONVENTION = "PER_DIEM_360"

# ---------------------------------------------------------------- scope validation
SINGLE_LINE_CAP_PCT = 0.50
MAX_REVISION_ROUNDS = 3

# ---------------------------------------------------------------- draws
RETAINAGE_PCT = {"INSPECTION": 0.10, "PHOTO": 0.20}
PHOTO_MAX_PCT = 0.50
PHOTO_MAX_REQUEST_CENTS = 3_000_000
PHOTO_MIN_PHOTOS_PER_LINE = 3
TRAVEL_BUFFER_MINUTES = 90

# ---------------------------------------------------------------- interest / servicing
DAY_BASIS_360 = 360
DAY_BASIS_365 = 365
DEFAULT_RATE_SPREAD_BPS = 600
BPS_DENOMINATOR = 10_000
DELINQUENCY_TO_DEFAULT_DAYS = 10

# ---------------------------------------------------------------- extensions / exit
EXTENSION_FEE_BPS = 100
EXTENSION_RATE_STEP_BPS = 50
MAX_EXTENSIONS = 2
EXIT_WATCH_DOM_DAYS = 90

# ---------------------------------------------------------------- foreclosure / REO
REDEMPTION_DAYS = 90
COMPLETION_BUDGET_CAP_PCT = 0.20
SELLING_COST_PCT = 0.06

# ---------------------------------------------------------------- envelopes
API_REQUEST_ID_PREFIX = "req_"
ERROR_META_KEYS = {"api_request_id", "api_request_timestamp"}
ERROR_DATA_KEYS = {"error_id", "message"}

# The six money buckets that participate in the commitment identity (PRD §2.5).
COMMITMENT_BUCKETS = (
    "funded_principal_cents",
    "undisbursed_holdback_cents",
    "reserved_release_cents",
    "interest_reserve_balance_cents",
    "decommitted_holdback_cents",
    "repaid_principal_cents",
)

# Balances deliberately OUTSIDE the commitment identity (PRD §2.5).
NON_IDENTITY_BALANCES = ("fee_balance_cents", "accrued_interest_unpaid_cents")
