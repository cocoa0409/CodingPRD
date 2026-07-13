"""Domain thresholds — numeric constants from the PRD calculations."""

# Material application recommendation (PRD §3.6)
MATERIAL_RATE = {
    "BASE_RATE_TONS_PER_LANE_MILE": 0.15,
    "TIER_MULT_ARTERIAL": 1.0,
    "TIER_MULT_RESIDENTIAL": 0.6,
    "TEMP_TIER_MILD": 0.8,       # t >= 30F
    "TEMP_TIER_MODERATE": 1.0,   # 20 <= t < 30
    "TEMP_TIER_COLD": 1.3,       # 10 <= t < 20
    "TEMP_TIER_FRIGID": 1.6,     # t < 10
}

# Overtime pay (PRD §3.7)
OVERTIME = {
    "DAILY_OT_THRESHOLD_HOURS": 8.0,
    "STORM_OT_THRESHOLD_HOURS": 6.0,
    "STANDARD_OT_MULTIPLIER": 1.5,
    "STORM_OT_MULTIPLIER": 2.0,
    "STANDARD_CALLOUT_MIN_HOURS": 2.0,
    "STORM_CALLOUT_MIN_HOURS": 3.0,
}

# Cost-per-event unit costs (PRD §3.9)
COST = {
    "SALT_UNIT_COST_CENTS": 8500,     # per ton
    "BRINE_UNIT_COST_CENTS": 25,      # per gallon
}

# Operator rest buffer (PRD §3.3)
OPERATOR_REST_BUFFER_HOURS = 8

# Pagination (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
