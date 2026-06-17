"""Domain thresholds — numeric constants from the PRD pricing/loyalty rules."""

# Loyalty tier thresholds (PRD §3.8, inclusive boundaries)
LOYALTY_TIER = {
    "SILVER_AT": 1000,
    "GOLD_AT": 5000,
}

# Tier earn multipliers, expressed as percent (PRD §3.8)
LOYALTY_MULTIPLIER_PCT = {
    "SILVER": 125,
    "GOLD": 150,
}

# Loyalty point value (PRD §3.5 / §3.4): 1 point == 1 cent on redemption
POINT_VALUE_CENTS = 1

# Pagination bounds (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
