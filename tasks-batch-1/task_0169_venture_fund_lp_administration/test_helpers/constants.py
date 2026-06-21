"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator used throughout rate math (PRD §2: one basis point
# is one hundredth of one percent).
BPS_DENOM = 10000

# Day-count denominator for the ACT/365 management-fee proration (PRD §3.8).
DAYS_PER_YEAR = 365

# The strike limit at which an ACTIVE commitment may be declared in default
# (PRD §3.2: the LP's default_strike_count must be at least one).
DEFAULT_STRIKE_LIMIT = 1

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Common test values reused across fixtures.
TEST_DEFAULTS = {
    "MGMT_FEE_RATE_BPS": 200,
    "CARRY_RATE_BPS": 2000,
    "PREF_RATE_BPS": 800,
    "GP_CATCHUP_RATE_BPS": 10000,
}
