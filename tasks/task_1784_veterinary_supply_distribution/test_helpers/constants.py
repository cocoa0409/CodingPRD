"""Domain thresholds — numeric constants named in the PRD."""

# Logical clock startup instant (PRD §2.4).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Order totals (PRD §3.4).
FREIGHT_FLAT_CENTS = 2500
EQUIPMENT_SURCHARGE_CENTS_PER_UNIT = 1500

# FEFO allocation shelf-life rule (PRD §3.5).
MIN_SHELF_LIFE_ON_DELIVERY_DAYS = 30

# Cold-chain temperature band, inclusive (PRD §2.10).
TEMP_MIN_CELSIUS = 2.0
TEMP_MAX_CELSIUS = 8.0

# Short-date credit tiers (PRD §3.9).
SHORT_DATE_WINDOW_DAYS = 180
TIER_FULL_CREDIT_DAYS = 30
TIER_HALF_CREDIT_DAYS = 90

# Short-date credit return window after approval (PRD §3.9 / §2.4).
CREDIT_RETURN_WINDOW_DAYS = 30

# Default delivery window (a Monday in the clock's first week).
DEFAULT_WINDOW_START = "2026-08-03T13:00:00Z"
DEFAULT_WINDOW_END = "2026-08-03T15:00:00Z"

# Default quarter label for the startup clock date (2026-08-01 -> 2026-Q3).
DEFAULT_QUARTER = "2026-Q3"

TEST_DEFAULTS = {
    "CLINIC_CREDIT_LIMIT_CENTS": 1000000,
    "CLINIC_MINIMUM_ORDER_CENTS": 5000,
    "CLINIC_DELIVERY_FREQUENCY_PER_WEEK": 5,
    "CLINIC_FREE_FREIGHT_THRESHOLD_CENTS": 75000,
    "UNIT_PRICE_CENTS": 2500,
    "LOT_QTY_ON_HAND": 10,
    "LOT_EXPIRY_DATE": "2027-06-30",
    "AUTH_QUARTERLY_QUANTITY_CAP": 100,
}
