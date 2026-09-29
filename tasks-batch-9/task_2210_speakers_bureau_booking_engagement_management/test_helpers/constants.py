"""Domain thresholds and rates taken from the PRD's arithmetic rules."""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
SECONDS_PER_WHOLE_DAY = 86400

# ---------------------------------------------------------------------------
# Qualification screens (PRD §3.2)
# ---------------------------------------------------------------------------

MIN_LEAD_TIME_WHOLE_DAYS = 21
BUDGET_FLOOR_CENTS = 250_000

# ---------------------------------------------------------------------------
# Quotation headroom (PRD §3.3)
# ---------------------------------------------------------------------------

BUDGET_TOLERANCE_MULTIPLIER = 1.20
MAX_LIVE_OPTIONS_PER_PROPOSAL = 4
MAX_REVISION_REQUESTS = 2
RANK_NO_MIN = 1
RANK_NO_MAX = 4

# ---------------------------------------------------------------------------
# Commission (PRD §3.5, §3.7, §3.8)
# ---------------------------------------------------------------------------

COMMISSION_PCT_MIN = 0.10
COMMISSION_PCT_MAX = 0.35

TIER_COMMISSION_PCT = {
    "BRONZE": 0.25,
    "SILVER": 0.22,
    "GOLD": 0.20,
}

# ---------------------------------------------------------------------------
# Invoice surcharge (PRD §3.7)
# ---------------------------------------------------------------------------

SURCHARGE_PCT = 0.0175

# ---------------------------------------------------------------------------
# Cancellation retention ladders and goodwill rebate (PRD §3.8)
# ---------------------------------------------------------------------------

STANDARD_LADDER_NO_RETENTION_DAYS = 30
STANDARD_LADDER_HALF_RETENTION_MIN_DAYS = 14
STRICT_LADDER_QUARTER_RETENTION_DAYS = 60
STRICT_LADDER_THREE_QUARTER_MIN_DAYS = 21

RETENTION_PCT_STANDARD = {
    "AT_OR_ABOVE_30_DAYS": 0.00,
    "14_TO_29_DAYS": 0.50,
    "UNDER_14_DAYS": 1.00,
}
RETENTION_PCT_STRICT = {
    "AT_OR_ABOVE_60_DAYS": 0.25,
    "21_TO_59_DAYS": 0.75,
    "UNDER_21_DAYS": 1.00,
}

REBATE_BAND_HIGH_MIN_CENTS = 500_000
REBATE_BAND_MID_MIN_CENTS = 200_000
REBATE_PCT_HIGH = 0.10
REBATE_PCT_MID = 0.05
REBATE_PCT_NONE = 0.00

# ---------------------------------------------------------------------------
# Travel reimbursement schedule (PRD §3.6)
# ---------------------------------------------------------------------------

DISTANCE_BAND_DAILY_RATE_CENTS = {
    "LOCAL": 15_000,
    "REGIONAL": 45_000,
    "NATIONAL": 90_000,
    "INTERNATIONAL": 180_000,
}

TRAVEL_CLASS_MULTIPLIER = {
    "ECONOMY": 1.00,
    "PREMIUM": 1.25,
    "BUSINESS": 1.60,
}

TRAVEL_BUFFER_DAYS_MIN = 0
TRAVEL_BUFFER_DAYS_MAX = 3
TRAVEL_BUFFER_DAYS_DEFAULT = 1

# ---------------------------------------------------------------------------
# Feedback scoring and tiering (PRD §3.9)
# ---------------------------------------------------------------------------

COMPOSITE_CONTENT_WEIGHT = 0.6
COMPOSITE_LOGISTICS_WEIGHT = 0.4
ROLLING_RAW_WEIGHTS = [0.5, 0.3, 0.2]
ROLLING_WINDOW_SIZE = 3
SCORE_MIN = 1
SCORE_MAX = 5

GOLD_MIN_DELIVERED = 4
GOLD_MIN_ROLLING_SCORE = 4.50
SILVER_MIN_DELIVERED = 2
SILVER_MIN_ROLLING_SCORE = 4.00

# ---------------------------------------------------------------------------
# Non-circumvention protection (PRD §3.9)
# ---------------------------------------------------------------------------

FULL_PROTECTION_MAX_DAYS = 180
HALF_PROTECTION_MAX_DAYS = 365
PROTECTION_FACTOR_FULL = 1.00
PROTECTION_FACTOR_HALF = 0.50
CREDIT_HOLD_STRIKE_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Exclusivity terms (PRD §3.5)
# ---------------------------------------------------------------------------

ALLOWED_EXCLUSIVITY_DAYS = [0, 30, 90, 180]

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
