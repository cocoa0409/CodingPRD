"""Domain constants and thresholds pinned by the specification."""

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
COLD_START_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Money and rounding
# --------------------------------------------------------------------------
HOUR_ROUNDING_INCREMENT = 0.25
IN_HOME_HOURS_PER_DAY = 8

# Overage tier snapshot thresholds, read against the employer's already
# accrued overage for the current benefit year.
OVERAGE_TIER_1_CENTS = 100000
OVERAGE_TIER_2_CENTS = 500000
OVERAGE_TIER_1_MULTIPLIER = 1.00
OVERAGE_TIER_2_MULTIPLIER = 0.90
OVERAGE_TIER_3_MULTIPLIER = 0.80

# --------------------------------------------------------------------------
# Ranking weights
# --------------------------------------------------------------------------
W_QUALITY = 0.45
W_CAPACITY = 0.30
W_MODE = 0.15
W_CONTINUITY = 0.10
PROBATION_FACTOR = 0.5
MODE_COMPONENT_CENTER_UNDER_EITHER = 1.0
MODE_COMPONENT_IN_HOME_UNDER_EITHER = 0.6
OFFER_TTL_HOURS = 48

# --------------------------------------------------------------------------
# Credentialing
# --------------------------------------------------------------------------
REQUIRED_CREDENTIAL_TYPES = ["LICENSE", "BACKGROUND_CHECK", "CPR", "INSURANCE"]
REINSTATE_MIN_LIFETIME_SCORE = 60

# --------------------------------------------------------------------------
# Quality scoring
# --------------------------------------------------------------------------
QUALITY_BASELINE = 100
SEVERITY_WEIGHTS = {"MINOR": 4, "MODERATE": 12, "SEVERE": 30}
DECAY_BAND_FRESH = 1.00      # incident age 0-30 days
DECAY_BAND_RECENT = 0.60     # 31-60 days
DECAY_BAND_STALE = 0.30      # 61-90 days
DECAY_BAND_EXPIRED = 0.00    # older than 90 days
BONUS_EVERY = 5
BONUS_STEP = 2
BONUS_CAP = 10

# --------------------------------------------------------------------------
# Service edges
# --------------------------------------------------------------------------
TRAVEL_BUFFER_MINUTES = 60
CHECK_IN_LEAD_MINUTES = 60
LATE_CANCEL_FACTOR = 0.5
NO_SHOW_STRIKE_LIMIT = 2
MAX_CARE_WINDOW_HOURS = 14

# --------------------------------------------------------------------------
# Renewal risk banding
# --------------------------------------------------------------------------
RISK_NO_SHOW_HIGH_PCT = 25
RISK_NO_SHOW_MEDIUM_PCT = 10
RISK_LIFETIME_FLOOR = 70

# --------------------------------------------------------------------------
# Declared field defaults
# --------------------------------------------------------------------------
DEFAULT_FISCAL_YEAR_START_MONTH = 1
DEFAULT_INVOICING_CYCLE = "MONTHLY"
DEFAULT_ADMIN_FEE_PCT = 0.085
DEFAULT_IN_HOME_MIN_BILLABLE_HOURS = 4
DEFAULT_MAX_DEPENDENTS_PER_RESERVATION = 3
DEFAULT_CANCELLATION_WINDOW_HOURS = 24
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 1
DEFAULT_DAILY_CAPACITY_SLOTS = 0

# --------------------------------------------------------------------------
# Field bounds
# --------------------------------------------------------------------------
ANNUAL_USE_LIMIT_DAYS_MIN = 1
ANNUAL_USE_LIMIT_DAYS_MAX = 60
COPAY_CENTS_MAX = 100000
OVERAGE_RATE_CENTS_MAX = 500000
NO_SHOW_CHARGE_CENTS_MAX = 200000
CANCELLATION_WINDOW_HOURS_MAX = 168
IN_HOME_MIN_BILLABLE_HOURS_MAX = 12
MAX_DEPENDENTS_MIN = 1
MAX_DEPENDENTS_MAX = 6
TOTAL_SLOTS_MAX = 500
DAILY_CAPACITY_SLOTS_MAX = 500
MAX_CONCURRENT_ASSIGNMENTS_MIN = 1
MAX_CONCURRENT_ASSIGNMENTS_MAX = 10
NARRATIVE_MIN_CHARS = 1
NARRATIVE_MAX_CHARS = 2000
USER_ID_MAX_CHARS = 80
FULL_NAME_MAX_CHARS = 200
RELATIONSHIP_MAX_CHARS = 40

# --------------------------------------------------------------------------
# Ledger memos written by the service
# --------------------------------------------------------------------------
MEMO_CONFIRM = "CONFIRM"
MEMO_COMPLETE_RELEASE = "COMPLETE_RELEASE"
MEMO_COMPLETE_COMMIT = "COMPLETE_COMMIT"
MEMO_COMPLETE_OVERAGE = "COMPLETE_OVERAGE"
MEMO_NO_SHOW_RELEASE = "NO_SHOW_RELEASE"
MEMO_NO_SHOW_COMMIT = "NO_SHOW_COMMIT"
MEMO_NO_SHOW = "NO_SHOW"
MEMO_CANCEL = "CANCEL"
MEMO_LATE_CANCEL = "LATE_CANCEL"
MEMO_PROVIDER_WITHDRAWN = "PROVIDER_WITHDRAWN"

# --------------------------------------------------------------------------
# Offer / reservation reason codes minted by the service
# --------------------------------------------------------------------------
REASON_REMATCHED = "REMATCHED"
REASON_OFFER_BATCH_CLOSED = "OFFER_BATCH_CLOSED"
REASON_CONFIRMED_ELSEWHERE = "CONFIRMED_ELSEWHERE"
REASON_RESERVATION_CANCELLED = "RESERVATION_CANCELLED"
REASON_OFFER_EXPIRED_SWEEP = "OFFER_EXPIRED"
UNFULFILLED_NO_ELIGIBLE_PROVIDER = "NO_ELIGIBLE_PROVIDER"
UNFULFILLED_CARE_WINDOW_ELAPSED = "CARE_WINDOW_ELAPSED"
STATUS_REASON_CREDENTIAL_REVIEW_PASSED = "CREDENTIAL_REVIEW_PASSED"

# --------------------------------------------------------------------------
# Maintenance sweep counters, in pinned order
# --------------------------------------------------------------------------
MAINTENANCE_COUNTERS = [
    "credentials_expired",
    "providers_suspended",
    "reservations_unfulfilled",
    "offers_expired",
    "blocks_closed",
    "reservations_no_showed",
    "reservations_withdrawn",
]
