"""Domain thresholds — numeric constants from the WIOA PRD calculations."""

# Rounding rates (PRD §2.5)
MILEAGE_RATE_CENTS_PER_MILE = 65.5

# OJT reimbursement-rate ceilings by employer size (PRD §3.6)
SMALL_EMPLOYER_RATE_CEILING = 0.75
LARGE_EMPLOYER_RATE_CEILING = 0.50

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Standard test-scenario amounts (used by fixtures/tests).
TEST_DEFAULTS = {
    "ITA_BUDGET_TOTAL": 5_000_000,
    "ITA_INDIVIDUAL_CAP": 800_000,
    "SUPPORTIVE_ANNUAL_CAP": 200_000,
    "PROGRAM_COST": 1_000_000,
}
