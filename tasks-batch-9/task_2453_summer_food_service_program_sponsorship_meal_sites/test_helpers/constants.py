"""Domain thresholds and rates stated in the PRD's calculation rules."""

# Site eligibility determination thresholds (percentages of free or reduced-price eligibility).
AREA_ELIGIBILITY_THRESHOLD_PCT = 50.00
CENSUS_ACS_THRESHOLD_PCT = 55.00

# Per-meal reimbursement rates in fractional cents, keyed by rate class then meal type.
RATE_CENTS = {
    "RURAL_OR_SELF_PREP": {
        "BREAKFAST": 268.75,
        "AM_SNACK": 126.25,
        "LUNCH": 470.50,
        "PM_SNACK": 126.25,
        "SUPPER": 470.50,
    },
    "OTHER": {
        "BREAKFAST": 263.25,
        "AM_SNACK": 123.00,
        "LUNCH": 462.75,
        "PM_SNACK": 123.00,
        "SUPPER": 462.75,
    },
}

# Claim reimbursement and budget ceilings.
ADMIN_CAP_PCT = 0.20
ADMIN_RATIO_MAX = 0.2000
ADVANCE_CAP_FRACTION = 0.25
MAX_RECOVERY_FRACTION = 1.00

# Point-of-service meal classification.
SECOND_MEAL_ALLOWANCE_PCT = 0.02

# Food safety holding rules.
COLD_MAX_F = 41.0
HOT_MIN_F = 135.0
MAX_HOLDING_MINUTES = 240

# Monitoring schedule compliance.
FIRST_WEEK_VISIT_DAYS = 4
FULL_REVIEW_DAYS = 28
MONITOR_DAILY_VISIT_CAP = 3
RESPONSE_DAYS_BY_SEVERITY = {"CRITICAL": 5, "MAJOR": 15, "MINOR": 30}

# Claim edit check.
COMPLIANCE_FLAG_THRESHOLD = 2

# Attendance forecast.
FORECAST_WINDOW_DAYS = 5
OUTREACH_UPLIFT_FACTOR = 1.10
DECAY_FACTOR = 0.6
WASTE_TOLERANCE_PCT = 0.10

# The logical clock's starting instant before any test moves it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Values reused by the canonical program-year scenario the tests build.
TEST_DEFAULTS = {
    "PROGRAM_YEAR": 2026,
    "SEASON_START_DATE": "2026-06-08",
    "SEASON_END_DATE": "2026-08-14",
    "OPERATING_COST_BUDGET_CENTS": 5_000_000,
    "ADMIN_COST_BUDGET_CENTS": 800_000,
    "PROJECTED_TOTAL_MEALS": 20_000,
    "APPROVED_OPERATING_COST_CENTS": 4_500_000,
    "APPROVED_ADMIN_COST_CENTS": 700_000,
    "APPROVED_MAX_ATTENDANCE": 200,
    "PLANNED_MEALS": 150,
    "FIRST_MEALS": 47,
}
