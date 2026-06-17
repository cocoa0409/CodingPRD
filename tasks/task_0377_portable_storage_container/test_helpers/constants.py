"""Domain thresholds — numeric constants from the PRD calculations (§3.4, §3.6, §3.9).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Move pricing (PRD §3.6)
MOVE_PRICING = {
    "LOCAL_BASE_CENTS": 8900,
    "LOCAL_PER_MILE_CENTS": 350,
    "BAND1_CENTS": 180,            # first 500 miles
    "BAND2_CENTS": 140,            # miles 500..1500
    "BAND3_CENTS": 110,            # miles above 1500
    "BAND1_LIMIT": 500,
    "BAND2_LIMIT": 1500,
    "FUEL_SURCHARGE_PCT": 0.12,
    "HANDLING_PER_CONTAINER_CENTS": 12500,
}

# Late fee (PRD §3.9)
LATE_FEE = {
    "GRACE_DAYS": 5,
    "DELINQUENT_DAYS": 20,
    "TIER1_SPAN_DAYS": 10,
    "LATE_FLAT_CENTS": 2500,
    "DAILY1_CENTS": 200,
    "DAILY2_CENTS": 500,
    "LATE_CAP_PCT": 0.50,
}

# Packing supplies (PRD §3.7)
PACKING_SUPPLIES = {
    "DEFAULT_TAX_RATE_BPS": 825,
    "BPS_DIVISOR": 10000,
}

# Protection premium (PRD §3.4)
PROTECTION = {
    "BPS_DIVISOR": 10000,
}

# Proration (PRD §3.4)
PRORATION = {
    "FIXED_DIVISOR": 30,
}

# Defaults reused by factories / fixtures
TEST_DEFAULTS = {
    "CLOCK": "2026-07-16T08:00:00Z",
    "C16_MONTHLY_RATE_CENTS": 19900,
    "C16_DELIVERY_FEE_CENTS": 8900,
    "C16_FOOTPRINT_SQFT": 160,
}
