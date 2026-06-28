"""Domain thresholds — numeric constants drawn from the PRD pricing and
scheduling rules (PRD §3.3, §3.6, §2.8)."""

# Coverage factors (PRD §3.3): FULL=1.00, PARTIAL=0.60, ACCENT=0.35.
COVERAGE_FACTORS = {
    "FULL": 1.00,
    "PARTIAL": 0.60,
    "ACCENT": 0.35,
}

# Per-line size surcharge in cents by size_class (PRD §3.2).
SIZE_SURCHARGE_CENTS = {
    "SEDAN": 0,
    "SUV": 15000,
    "TRUCK": 25000,
}

# Deposit rate (PRD §3.3): net * 2500 bps / 10000 = quarter of net, round-half-up.
DEPOSIT_RATE_BPS = 2500

# Rush tier basis points keyed off net_cents (PRD §3.3).
RUSH_BPS_HIGH = 500   # net_cents >= 100000
RUSH_BPS_MID = 800    # 50000 <= net_cents < 100000
RUSH_BPS_LOW = 1200   # net_cents < 50000
RUSH_TIER_HIGH_CENTS = 100000
RUSH_TIER_MID_CENTS = 50000

# Quote time-to-live in days (PRD §3.5).
QUOTE_TTL_DAYS = 30

# Installer front rest buffer in minutes (PRD §3.6).
INSTALLER_REST_BUFFER_MINUTES = 45

# Default logical clock before any operator sets it (PRD §2.8).
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}
