"""Domain thresholds — numeric constants from PRD calculations and windows.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Post-termination exercise window (months) added to grant_date + vesting_months
# before an ACTIVE grant may be expired (PRD §3.6).
PTE_MONTHS = 3

# Day count used to annualize NOTE interest accrual (PRD §3.10).
DAYS_PER_YEAR = 365

# Section 83(b) filing window in days; inclusive at the 30-day boundary (PRD §3.9).
SECTION_83B_WINDOW_DAYS = 30

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Convenient default test values reused across factories/fixtures.
TEST_DEFAULTS = {
    "AUTHORIZED_SHARES": 10_000_000,
    "POOL_SHARES": 100_000,
    "VESTING_MONTHS": 48,
    "CLIFF_MONTHS": 12,
}
