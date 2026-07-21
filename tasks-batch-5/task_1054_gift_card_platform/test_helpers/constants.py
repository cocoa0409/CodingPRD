"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

# Default server logical-clock instant at startup (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

THRESHOLDS = {
    # Estimated breakage recognition (PRD §3.6): 1000 bps = 10% of balance.
    "BREAKAGE_RATE_BPS": 1000,
    # Tiered interchange fee (PRD §3.7).
    "TIER1_MAX_CENTS": 1_000_000,
    "TIER1_RATE_BPS": 300,
    "TIER2_MAX_CENTS": 5_000_000,
    "TIER2_RATE_BPS": 250,
    "TIER3_RATE_BPS": 200,
    "MIN_INTERCHANGE_CENTS": 2500,
    # Dormancy accrual (PRD §3.6).
    "DORMANCY_DAYS": 365,
    "DORMANCY_FEE_CENTS": 200,
    # Campaign window buffer (PRD §3.2).
    "CAMPAIGN_GAP_DAYS": 7,
}

# Program design defaults (PRD §3.2).
PROGRAM_DEFAULTS = {
    "BREAKAGE_METHOD": "REMITTANCE",
    "EXPIRY_MONTHS": 12,
    "MAX_BALANCE_CENTS": 100_000,
    "MIN_LOAD_CENTS": 500,
    "CURRENCY": "USD",
}

# VelocityRule defaults (PRD §3.2).
VELOCITY_DEFAULTS = {
    "WINDOW_HOURS": 24,
    "MAX_COUNT": 5,
    "MAX_AMOUNT_CENTS": 50_000,
    "ENABLED": True,
}
