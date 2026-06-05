"""Domain thresholds and constants (PRD §3.8, §3.9, §3.11, §3.6)."""

# Franchise-tax bases in integer cents (PRD §3.8).
BASE_BY_STATE = {
    "CA": {"LLC": 80000, "CORP": 80000, "LP": 80000},
    "DE": {"LLC": 30000, "CORP": 17500, "LP": 30000},
    "NY": {"LLC": 2500, "CORP": 2500, "LP": 2500},
    "TX": {"LLC": 0, "CORP": 0, "LP": 0},
    "FL": {"LLC": 13875, "CORP": 15000, "LP": 50000},
    "WY": {"LLC": 6000, "CORP": 6000, "LP": 10000},
}

# Revenue-tier multiplier (×100). 1.00 → 100, 1.10 → 110, etc. (PRD §3.8).
TIER_MULT_X100 = {
    "ZERO": 100,
    "MICRO": 100,
    "SMALL": 110,
    "MEDIUM": 125,
    "LARGE": 150,
}

# Per-state assessed-variant minimum floor in cents (PRD §3.8).
MIN_FLOOR_BY_STATE = {
    "CA": 80000,
    "DE": 17500,
    "NY": 2500,
    "TX": 0,
    "FL": 13875,
    "WY": 6000,
}

# Per-state daily late-fee rate in cents × 100 (PRD §3.9).
DAILY_RATE_BY_STATE_X100 = {
    "CA": 5550,
    "DE": 11100,
    "NY": 2250,
    "TX": 0,
    "FL": 7775,
    "WY": 3325,
}

# Late-fee cap (PRD §3.9).
LATE_FEE_CAP_CENTS = 25_000_000

# BOI deadline grace windows (PRD §3.11).
GRACE_DAYS_BY_TRIGGER = {
    "FORMATION": 90,
    "AMENDMENT": 30,
    "ANNUAL_REFRESH": 30,
}

# BOI staleness / refresh window in days (PRD §3.6).
BOI_REFRESH_DAYS = 365

# Supported states (PRD §3.1).
SUPPORTED_STATES = {"CA", "DE", "NY", "TX", "FL", "WY"}

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
