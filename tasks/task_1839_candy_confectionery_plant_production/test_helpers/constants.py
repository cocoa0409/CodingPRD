"""Domain thresholds and shared geometry — numeric constants from the PRD."""

# Seasonal stock is never priced below the floor (PRD §3.8).
MIN_PRICE_FLOOR_CENTS = 50

# Gift-kit discount applied per component line before summing (PRD §3.6).
GIFT_KIT_DISCOUNT_PCT = 0.10

# Bloom holds at or above this rounded defect rate cannot be released (PRD §3.7).
BLOOM_RELEASE_MAX_PCT = 2.00

# The logical clock at server startup, before any client intervention (PRD §2.5).
STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# Shared setup geometry used across fixtures.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
DEFAULT_BUILD_START = "2026-09-01T00:00:00Z"
DEFAULT_BUILD_END = "2026-10-15T00:00:00Z"
DEFAULT_SHIP_START = "2026-11-01T00:00:00Z"
DEFAULT_SHIP_END = "2026-12-26T00:00:00Z"

TEST_DEFAULTS = {
    "QTY_ON_HAND": 100000,
    "UNITS_PER_COMPONENT": 10,
    "LEAD_TIME_DAYS": 14,
    "TARGET_UNITS": 5000,
    "BASE_PRICE_CENTS": 800,
    "SHELF_LIFE_DAYS": 200,
    "STANDARD_YIELD_PCT": 0.95,
}
