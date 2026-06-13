"""Domain thresholds — numeric constants from the PRD calculations and limits."""

# Peak-date surcharge (PRD 3.5 estimate pricing)
PEAK = {
    "FLAT_CENTS": 2500,            # subtotal < 20000 -> flat 2500
    "MID_RATE": 0.10,             # 20000 <= subtotal < 50000 -> subtotal * 0.10 (round half-up)
    "HIGH_RATE": 0.15,           # subtotal >= 50000 -> subtotal * 0.15 (round half-up)
    "MID_TIER_FLOOR_CENTS": 20000,
    "HIGH_TIER_FLOOR_CENTS": 50000,
    "CAPACITY_RATIO": 0.80,      # peak-day effective capacity = floor(unit_capacity * 0.80)
}

# Tiered deposit ratio (PRD 3.5 deposit_calc)
DEPOSIT = {
    "FLOOR_CENTS": 5000,
    "STANDARD_RATIO": 0.30,
    "PEAK_RATIO": 0.50,
    "COMPLEX_RATIO": 0.60,
}

# Complex-bake threshold (PRD 3.1)
COMPLEX_TIER_LEVELS = 3

# Loyalty tiers by lifetime spend (PRD 3.2)
LOYALTY = {
    "SILVER_FLOOR_CENTS": 50000,    # STANDARD < 50000, SILVER 50000..149999, GOLD >= 150000
    "GOLD_FLOOR_CENTS": 150000,
}

# Pagination bounds (PRD 2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

# Delivery window bounds (PRD 3.11)
WINDOW_MIN = 0
WINDOW_MAX = 1439

# A syntactically valid UUID that never resolves to a row.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
