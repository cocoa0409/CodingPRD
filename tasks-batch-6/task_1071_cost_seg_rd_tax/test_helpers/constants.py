"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# MACRS first-year rates by asset class (§3.3)
MACRS_Y1_RATE = {
    "FIVE_YEAR": 0.20,
    "SEVEN_YEAR": 0.1429,
    "FIFTEEN_YEAR": 0.05,
    "THIRTY_NINE_YEAR": 0.02564,
}

# Bonus-depreciation percentage by placed-in-service calendar year (§3.3)
BONUS_PCT_BY_YEAR = {
    2022: 1.00,
    2023: 0.80,
    2024: 0.60,
    2025: 0.40,
    2026: 0.20,
}

# Bonus-eligible asset classes (§3.3)
BONUS_ELIGIBLE_CLASSES = ["FIVE_YEAR", "SEVEN_YEAR", "FIFTEEN_YEAR"]

RECOVERY_PERIOD_YEARS = {
    "FIVE_YEAR": 5,
    "SEVEN_YEAR": 7,
    "FIFTEEN_YEAR": 15,
    "THIRTY_NINE_YEAR": 39,
}

# R&D credit rates (§3.4)
ASC_RATE = 0.14
ASC_STARTUP_RATE = 0.06
REGULAR_RATE = 0.20

# Contract-research cap on qualified percent (§3.4)
CONTRACT_RESEARCH_CAP = 0.65

# Fee cap in basis points (§3.2)
MAX_FEE_BPS = 3000

# Amended-return statute of limitations in years (§3.6)
AMEND_STATUTE_YEARS = 3

# Logical-clock startup default (§2.6)
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00.000Z"

# Pagination defaults (§2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
