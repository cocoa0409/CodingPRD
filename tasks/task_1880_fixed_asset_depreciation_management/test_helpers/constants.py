"""Domain thresholds and rate tables from PRD §3 calculations."""

# PRD §3.3: statutory MACRS annual rate tables.
MACRS_5_RATES = [0.2000, 0.3200, 0.1920, 0.1152, 0.1152, 0.0576]
MACRS_7_RATES = [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446]

# PRD §3.3: year-1 bonus expensing share when bonus_elected is true.
BONUS_RATE_PCT = 0.60

# PRD §3.5: day-of-month at or after which a disposal posts final-period entries.
MID_MONTH_CUTOFF_DAY = 15

# PRD §3.7: property-tax mill rate applied to assessed value.
MILL_RATE = 0.0125

# Standard test asset class: threshold 250000 cents, 60-month life,
# straight-line book, MACRS 5-year tax, bonus disallowed.
DEFAULT_CLASS = {
    "CLASS_CODE": "MACH",
    "NAME": "Machinery",
    "CAPITALIZATION_THRESHOLD_CENTS": 250000,
    "DEFAULT_USEFUL_LIFE_MONTHS": 60,
    "BOOK_METHOD": "STRAIGHT_LINE",
    "TAX_METHOD": "MACRS_5YR",
    "BONUS_DEPRECIATION_ALLOWED": False,
}

TEST_DEFAULTS = {
    "COST_CENTER": "CC1",
    "LOCATION": "PLANT-1",
    "IN_SERVICE_DATE": "2026-01-10",
    "FIRST_PERIOD": "2026-01",
}
