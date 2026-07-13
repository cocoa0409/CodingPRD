"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.4, §3.6, §3.7, §3.8)."""

# Server startup default logical clock (PRD §2.7).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Final-price calculation constants (PRD §3.6).
BUNDLE_MIN_ADDONS = 3
BUNDLE_DISCOUNT_BPS = 1000
MAX_BUNDLE_DISCOUNT_CENTS = 5000
AFTER_HOURS_FLAT_CENTS = 4000
AFTER_HOURS_BPS = 1500
STANDARD_START_HOUR_UTC = 8
STANDARD_END_HOUR_UTC = 18

# Payout / commission constants (PRD §3.7, §3.8).
PLATFORM_COMMISSION_BPS = 2500
REDO_PENALTY_CENTS = 3000

# Dispatch selector travel buffer (PRD §3.4).
TRAVEL_BUFFER_MINUTES = 30

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 12000,
    "COMMISSION_RATE_BPS": 1000,
    "WARRANTY_DAYS": 30,
    "MAX_CONCURRENT_APPOINTMENTS": 5,
}
