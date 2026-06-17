"""Domain thresholds — numeric constants from the PRD's fee and budget calculations."""

# Budget health tiers (PRD §3.8): utilization <= 0.80 GREEN; <= 1.00 AMBER; > 1.00 RED.
BUDGET_THRESHOLDS = {
    "GREEN_CEIL": 0.80,
    "AMBER_CEIL": 1.00,
}

# HOURLY fee quarter-hour billing (PRD §3.9): minutes / 15 rounded up, each = 0.25h.
FEE_CONSTANTS = {
    "MINUTES_PER_QUARTER": 15,
    "QUARTER_HOUR_FRACTION": 0.25,
}

# Test defaults used by fixtures/factories.
TEST_DEFAULTS = {
    "LARGE_BUDGET": 100_000_000,
    "FLAT_FEE": 100_000,
}
