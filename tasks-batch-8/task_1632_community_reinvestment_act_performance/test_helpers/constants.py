"""Domain thresholds — numeric constants from PRD §2.5, §2.8, §3.3, §3.4, §3.5, §3.7, §3.9."""

# Logical clock (PRD §2.5): startup default, never wall-clock.
LOGICAL_CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
LOGICAL_CLOCK_DEFAULT_DATE = "2026-08-01"

# Lending (PRD §3.3): inclusive $1MM gross-annual-revenue threshold, in cents.
SMALL_REVENUE_THRESHOLD_CENTS = 100_000_000

# CRA register totals (PRD §3.9): $1MM reportable cap and $1,000 rounding unit.
CRA_REPORTABLE_CAP_CENTS = 100_000_000
REGISTER_ROUND_UNIT_CENTS = 100_000

# CD qualification (PRD §3.4): FULL_COUNT requires lmi_benefit_pct >= 0.51.
FULL_COUNT_LMI_THRESHOLD = 0.51

# Branch closure notice (PRD §3.5): at least 90 days.
CLOSURE_NOTICE_MIN_DAYS = 90

# Exam composite (PRD §3.7): points, weights, inclusive band lower bounds.
RATING_POINTS = {
    "OUTSTANDING": 10,
    "SATISFACTORY": 6,
    "NEEDS_TO_IMPROVE": 2,
    "SUBSTANTIAL_NONCOMPLIANCE": 0,
}
W_LENDING = 0.5
W_INVESTMENT = 0.25
W_SERVICE = 0.25
BAND_OUTSTANDING = 8.50
BAND_SATISFACTORY = 5.00
BAND_NEEDS_TO_IMPROVE = 2.50

# Branch access score (PRD §3.9).
ACCESS_BASE_SCORE = 50
ACCESS_DISPERSION_WEIGHT = 100
ACCESS_LMI_CLOSURE_PENALTY = 5
ACCESS_SCORE_FLOOR = 0
ACCESS_SCORE_CEILING = 100

TEST_DEFAULTS = {
    "AREA_BUDGET_CENTS": 10_000_000,
    "AREA_START_DATE": "2023-01-01",
}
