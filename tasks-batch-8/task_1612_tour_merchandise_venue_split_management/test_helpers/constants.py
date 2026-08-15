"""Domain thresholds and shared defaults from the PRD."""

# Default tour royalty configuration used by most scenarios.
DEFAULT_STANDARD_RATE_BPS = 1000
DEFAULT_TIER_THRESHOLD_CENTS = 500000
DEFAULT_TIER_BONUS_BPS = 500
DEFAULT_LICENSED_FLAT_PER_UNIT_CENTS = 500
DEFAULT_LICENSED_RATE_BPS = 2000
DEFAULT_CASH_VARIANCE_TOLERANCE_CENTS = 1000

DEFAULT_ROYALTY_CONFIG = {
    "standard_rate_bps": DEFAULT_STANDARD_RATE_BPS,
    "tier_threshold_cents": DEFAULT_TIER_THRESHOLD_CENTS,
    "tier_bonus_bps": DEFAULT_TIER_BONUS_BPS,
    "licensed_flat_per_unit_cents": DEFAULT_LICENSED_FLAT_PER_UNIT_CENTS,
    "licensed_rate_bps": DEFAULT_LICENSED_RATE_BPS,
}

# The tour's built-in default size curve (PRD §3.1).
DEFAULT_SIZE_CURVE = {"S": 1, "M": 2, "L": 2, "XL": 1}

# Common operational values.
DEFAULT_CASH_FLOAT_CENTS = 5000
DEFAULT_FLAT_COMMISSION_BPS = 1500
DEFAULT_SHOW_DATE = "2026-08-10T20:00:00Z"

# The logical clock reads this exact instant before any clock-setting call.
INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Restock lead time, in hours (dispatch instant vs destination show_date).
LEAD_TIME_HOURS = 48
