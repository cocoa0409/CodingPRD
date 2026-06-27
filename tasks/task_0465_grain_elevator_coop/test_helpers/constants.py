"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Storage charge (PRD §3.6): $0.0005 per bushel per day, 30-day grace.
STORAGE_RATE_PER_BU_PER_DAY = 0.0005
GRACE_DAYS = 30

# Margin / mark-to-market (PRD §3.8).
INITIAL_MARGIN_PER_CONTRACT = 2000
MAINTENANCE_MARGIN_PER_CONTRACT = 1500

# Default futures contract size when omitted at commodity create (PRD §3.1).
DEFAULT_FUTURES_CONTRACT_BUSHELS = 5000

# Dryer cleanout buffer default (PRD §3.2).
DEFAULT_CLEANOUT_BUFFER_MINUTES = 30

# Pagination (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0

# Logical clock default at startup (PRD §2.9).
CLOCK_START = "2026-01-01T00:00:00Z"

# Standard reference commodity inputs used across fixtures.
CORN_DEFAULTS = {
    "symbol": "CORN",
    "test_weight_lbs_per_bushel": 56,
    "base_moisture_pct": 15.0,
    "shrink_pct_per_point": 1.4,
    "drying_cents_per_point_per_bushel": 4,
}

WHEAT_DEFAULTS = {
    "symbol": "WHEAT",
    "test_weight_lbs_per_bushel": 60,
    "base_moisture_pct": 13.5,
    "shrink_pct_per_point": 1.2,
    "drying_cents_per_point_per_bushel": 3,
}
