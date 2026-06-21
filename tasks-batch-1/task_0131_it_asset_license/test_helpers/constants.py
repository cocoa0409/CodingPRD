"""Domain thresholds and shared numeric constants from the PRD calculations."""

# Depreciation / renewal calculation constants (PRD Section 2.6, 3.2, 3.5).
MONTHS_PER_YEAR = 12

# Default useful-life horizon for a hardware asset when not supplied (PRD Section 3.2).
DEFAULT_USEFUL_LIFE_MONTHS = 36

# Default employee assignment cap (PRD Section 3.1).
DEFAULT_MAX_ASSIGNED_ASSETS = 3

# Over-deploy boundary for true-up verdict: position_units strictly < 0 is
# OVER_DEPLOYED; exactly 0 is COMPLIANT (PRD Section 3.7).
OVER_DEPLOY_BOUNDARY = 0

# Convenient ISO 8601 UTC instants reused across fixtures.
TEST_DEFAULTS = {
    "PURCHASE_COST_CENTS": 100000,
    "DEPRECIATION_PURCHASE_COST_CENTS": 360000,
    "DEPRECIATION_IN_SERVICE_DATE": "2024-01-01T00:00:00.000Z",
    "DEPRECIATION_CLOCK": "2025-07-15T00:00:00.000Z",
    "TERM_START": "2025-01-01T00:00:00.000Z",
    "TERM_END": "2025-12-31T00:00:00.000Z",
}
