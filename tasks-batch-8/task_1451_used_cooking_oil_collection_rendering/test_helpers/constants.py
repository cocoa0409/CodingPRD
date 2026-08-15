"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # PRD §3.6 grade bands (lower bound inclusive, upper bound exclusive)
    "GRADE_A_MAX_MOISTURE": 5.0,
    "GRADE_B_MAX_MOISTURE": 15.0,
    "GRADE_C_MAX_MOISTURE": 25.0,
    "GRADE_A_MAX_IMPURITY": 2.0,
    "GRADE_B_MAX_IMPURITY": 6.0,
    "GRADE_C_MAX_IMPURITY": 10.0,
    # PRD §3.7 grade factors
    "GRADE_FACTOR_A": 1.00,
    "GRADE_FACTOR_B": 0.90,
    "GRADE_FACTOR_C": 0.75,
    "GRADE_FACTOR_REJECT": 0.00,
    # PRD §3.4 tank reconciliation tolerance
    "TANK_TOLERANCE_GAL": 0.5,
    # PRD §3.9 fixed rendering yield coefficient
    "YIELD_COEFF": 0.92,
    # PRD §3.1/§3.3 missed-pickup suspension rule
    "MISSED_PICKUP_SUSPEND_THRESHOLD": 3,
    "MISSED_PICKUP_WINDOW_DAYS": 90,
    # PRD §3.7 disbursement floor
    "MIN_PAYOUT_CENTS": 100,
    # PRD §3.2 cooling-off window
    "COOLING_OFF_DAYS": 14,
    # PRD §3.8 complaint reopen window
    "COMPLAINT_REOPEN_WINDOW_DAYS": 7,
    # PRD §3.3 container capacity schema bounds
    "CONTAINER_MIN_CAPACITY_GAL": 30,
    "CONTAINER_MAX_CAPACITY_GAL": 2000,
}

# Logical-clock startup default per PRD §2.4.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "INDEX_CODE": "YG_CBI",
    "SITE_MAX_CONTAINER_GAL": 5000,
    "FLOOR_CENTS_PER_GAL": 50,
    "CAP_CENTS_PER_GAL": 150,
    "DRIVER_REF": "drv-1",
}
