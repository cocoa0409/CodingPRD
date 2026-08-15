"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD section 2.5).
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# Braking-action thresholds on mu_value; lower bounds are inclusive (PRD 3.5).
BRAKING_GOOD_MIN = 0.50
BRAKING_MEDIUM_MIN = 0.36
BRAKING_MEDIUM_POOR_MIN = 0.26
BRAKING_POOR_MIN = 0.10

# Chemical temperature-factor branches (PRD 3.8).
TEMP_LOW_F = 15
TEMP_HIGH_F = 28
FACTOR_COLD = 1.25
FACTOR_COOL = 1.10
FACTOR_WARM = 1.00

# Condition-code downgrade rule (PRD 3.4).
DOWNGRADE_COVERAGE_PCT = 50
DOWNGRADE_DEPTH_IN = 0.25

# Shift labor overtime rule (PRD 3.10).
OT_MULTIPLIER = 1.5
REGULAR_HOURS_CAP = 8

# Product CONSTRAINED trigger: dispensed >= 90% of seasonal limit (PRD 3.7).
CONSTRAINED_THRESHOLD_PCT = 0.9

# Activation fleet readiness floor (PRD 3.1).
MIN_READY_UNITS_FOR_ACTIVATION = 3

TEST_DEFAULTS = {
    "SEASON_LABEL": "2025-2026",
    "CHEMICAL_LIMIT_LBS": 100000,
    "BUDGET_CENTS": 5000000,
    "SURFACE_LENGTH_FT": 5000,
    "SURFACE_WIDTH_FT": 150,
    "PRODUCT_BASE_RATE": 30,
    "PRODUCT_UNIT_COST": 12,
    "PRODUCT_SEASONAL_LIMIT": 100000,
    "SHIFT_BASE_RATE": 5000,
    "UNIT_HOURLY_RATE": 14500,
    "OBSERVED_AT": "2026-08-01T00:00:00Z",
    "SHIFT_START": "2026-08-10T08:00:00Z",
    "SHIFT_END": "2026-08-10T16:00:00Z",
}
