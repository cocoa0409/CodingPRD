"""Domain thresholds — numeric constants from PRD pricing and scheduling rules."""

# Default demand-band bounds (PRD section 3.2).
PRICING_DEFAULTS = {
    "LOW_DEMAND_MAX_RATIO": 0.5,
    "HIGH_DEMAND_MIN_RATIO": 0.8,
    "MID_SURGE_PCT": 20,
    "HIGH_SURGE_PCT": 50,
}

# Actor-shift rest buffer (PRD section 3.8): a mandatory thirty-minute rest buffer.
SHIFT_REST_MINUTES = 30

# Common test values reused across boundary / pricing setups.
TEST_DEFAULTS = {
    "GA_BASE_PRICE_CENTS": 2410,
}
