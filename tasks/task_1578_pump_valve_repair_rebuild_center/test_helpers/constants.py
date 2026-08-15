"""Domain thresholds and shared values from the PRD's calculation rules."""

# Logical clock (PRD §2.4): startup default and the derived quote validity end.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
QUOTE_VALIDITY_DAYS = 14
DEFAULT_QUOTE_EXPIRES_UTC = "2026-08-15T00:00:00Z"  # issued_at + 14 days

# Test verdict tolerance (PRD §3.7): inclusive boundary.
TOLERANCE_PCT = 5.0

# Certification set-pressure tolerance (PRD §3.8): inclusive +/-3%.
SET_PRESSURE_TOLERANCE_RATIO = 0.03

# Window posture (PRD §3.6): SURGE at >= ceil(0.8 * capacity), FULL at >= capacity.
SURGE_THRESHOLD_PCT = 0.8

# Surge multiplier levers (PRD §3.6).
SURGE_POSTURE_BASE = 1.25
NORMAL_POSTURE_BASE = 1.00
SURGE_PRIORITY_ADD = 0.15
POOL_PROGRAM_CREDIT = 0.10
MULTIPLIER_FLOOR = 1.00
MULTIPLIER_CAP = 1.50

# Warranty pricing (PRD §3.5).
WARRANTY_PART_DISCOUNT_PCT = 0.5

# Certification tag numbering (PRD §3.8).
TAG_NUMBER_PREFIX = "SVT-"
FIRST_TAG_NUMBER = "SVT-000001"

# Default window / service-window values used across setups.
DEFAULT_WINDOW_START = "2026-06-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-07-01T00:00:00Z"
DEFAULT_PLANNED_START = "2026-08-10"
DEFAULT_PLANNED_END = "2026-08-20"

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 99_999_999,
    "WARRANTY_TERMS_DAYS": 365,
    "WINDOW_CAPACITY": 1000,
    "ESTIMATED_BAY_HOURS": 5,
    "LABOR_HOURS": 1,
    "LABOR_RATE_CENTS": 20000,
    "UNIT_PRICE_CENTS": 5000,
    "RATED_FLOW_GPM": 500,
    "SET_PRESSURE_PSIG": 100,
}

# Measured-point builders for common verdict scenarios (deviation vs reference 100).
POINT_ZERO_DEVIATION = {"duty_pct": 100, "measured_value": 100, "reference_value": 100}
POINT_AT_TOLERANCE = {"duty_pct": 100, "measured_value": 105, "reference_value": 100}
POINT_OVER_TOLERANCE = {"duty_pct": 100, "measured_value": 105.01, "reference_value": 100}
POINT_CLEAR_FAIL = {"duty_pct": 100, "measured_value": 110, "reference_value": 100}
# Deviations +8.00 / -8.00 / -2.00: PER_POINT fails (max 8.00), WEIGHTED_AVG passes (-1.33).
VARIANT_POINTS = [
    {"duty_pct": 80, "measured_value": 108, "reference_value": 100},
    {"duty_pct": 100, "measured_value": 92, "reference_value": 100},
    {"duty_pct": 120, "measured_value": 98, "reference_value": 100},
]
