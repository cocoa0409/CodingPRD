"""Domain thresholds — numeric constants from the PRD's money calculations."""

# Labor rates (cents per hour), PRD 3.3
LABOR_RATE_STANDARD = 5000
LABOR_RATE_MASTER = 8000

# Diagnostic fee (cents), waived under warranty. PRD 3.3
DIAGNOSTIC_FEE_CENTS = 4000

# Repair-vs-replace threshold percentage. PRD 3.3
REPLACE_THRESHOLD_PCT = 0.60

# Trade-in payout multipliers. PRD 3.7
GRADE_MULTIPLIER = {"A": 0.90, "B": 0.70, "C": 0.45, "D": 0.20}
ACCESSORY_BONUS_PCT = 0.05
COSMETIC_DEDUCT_PCT = 0.03

# Protection-plan coverage. PRD 3.8
DEDUCTIBLE_BY_PLAN = {"ADH": 7500, "EXTENDED_WARRANTY": 0, "ACCESSORY": 2500}
COVERAGE_CAP_CENTS = 50000

# Warranty callback window (days). PRD 3.6
WARRANTY_DAYS = 90

# Server logical-clock startup default. PRD 2.5
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination. PRD 2.3
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

TEST_DEFAULTS = {
    "SPEND_CAP": 100_000,
    "MARKET_VALUE": 60_000,
    "PART_PRICE": 6_000,
    "PART_STOCK": 10,
}
