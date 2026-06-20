"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3.4, §3.8)."""

# Re-entry / pre-harvest window math (PRD §3.4).
HOURS_PER_DAY = 24

# Irrigation overlap soil-saturation buffer (PRD §3.8): closed interval + 6h on each side.
IRRIGATION_BUFFER_HOURS = 6

# Final cost-per-acre denominator guard (PRD §3.7).
MIN_DENOMINATOR_GUARD = 1

# Monetary / quantity rounding precision (PRD §2.8).
MONEY_DECIMAL_PLACES = 2

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Reusable test values.
TEST_DEFAULTS = {
    "ACREAGE": 100.0,
    "SEASON_YEAR": 2026,
}
