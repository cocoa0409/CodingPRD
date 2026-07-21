"""Domain thresholds — numeric constants from PRD calculations."""

# Volume-discount tier boundaries (grams) and rates (§3.6).
DISCOUNT = {
    "TIER1_GRAMS": 500,     # [500, 2000) -> 5%
    "TIER2_GRAMS": 2000,    # [2000, +inf) -> 12%
    "TIER1_RATE": 0.05,
    "TIER2_RATE": 0.12,
}

# Blend component ratio total in basis points (§3.1).
BPS_TOTAL = 10000

# Station cleaning buffer between consecutive runs, in minutes (§3.4).
STATION_BUFFER_MINUTES = 30

# Default product shelf life when omitted (§3.1).
DEFAULT_SHELF_LIFE_DAYS = 365

# Server logical-clock startup default (§2.7).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"
