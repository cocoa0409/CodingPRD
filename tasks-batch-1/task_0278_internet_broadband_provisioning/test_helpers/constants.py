"""Domain thresholds — numeric constants from PRD calculations and §2.8 geometry."""

# Overage tier ladder (PRD §3.10)
OVERAGE = {
    "TIER1_LIMIT_GB": 50,
    "TIER1_RATE_CENTS": 50,
    "TIER2_LIMIT_GB": 50,
    "TIER2_RATE_CENTS": 30,
    "TIER3_RATE_CENTS": 20,
    "OVERAGE_CAP_CENTS": 6000,
}

# Outage SLA credit (PRD §3.6)
OUTAGE = {
    "MIN_QUALIFYING_MINUTES": 240,
}

# Monthly bill promo (PRD §3.10)
PROMO = {
    "PROMO_LOW_CENTS": 8000,
    "PROMO_LOW_OFF_CENTS": 500,
    "PROMO_HIGH_CENTS": 10000,
    "PROMO_HIGH_OFF_CENTS": 1000,
}

# Canonical cycle geometry (PRD §2.8)
CYCLE_DAYS = 30
CYCLE_MINUTES = 43200

# Default technician travel buffer (PRD §3.1)
DEFAULT_TRAVEL_BUFFER_MINUTES = 30
