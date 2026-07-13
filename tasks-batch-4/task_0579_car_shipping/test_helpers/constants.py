"""Domain thresholds — numeric constants from the Car Shipping PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework (re-exported via __init__).
"""

# Quote pricing (PRD §3.3) — marginal mileage bands and surcharge/discount rates.
QUOTE_PRICING = {
    "BAND1_RATE_CENTS_PER_MILE": 95,
    "BAND2_RATE_CENTS_PER_MILE": 75,
    "BAND3_RATE_CENTS_PER_MILE": 60,
    "BAND1_MAX_MILES": 500,
    "BAND2_MAX_MILES": 1500,
    "INOP_SURCHARGE_CENTS": 15000,
    "ENCLOSED_PCT": 0.40,
    "EXPEDITE_PCT": 0.25,
    "MULTI_CAR_PCT_PER_EXTRA": 0.05,
    "MULTI_CAR_MAX_PCT": 0.15,
    "QUOTE_TTL_HOURS": 72,
}

# Deposit split (PRD §3.3).
DEPOSIT_SPLIT = {
    "DEPOSIT_PCT": 0.20,
    "DEPOSIT_FLOOR_CENTS": 10000,
    "DEPOSIT_CAP_CENTS": 40000,
}

# Terminal dock overlap (PRD §3.1 / §3.2).
DEFAULT_TERMINAL_BUFFER_MINUTES = 60

# Logical clock (PRD §2.6) — server startup default.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
