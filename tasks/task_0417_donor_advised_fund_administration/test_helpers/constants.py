"""Domain thresholds — numeric constants from PRD calculations and policy defaults."""

# Sponsor policy defaults (PRD Section 3.1)
SPONSOR_DEFAULTS = {
    "MINIMUM_GRANT_CENTS": 5000,
    "INACTIVITY_QUARTERS": 8,
    "ADMIN_FEE_BPS_DEFAULT": 50,
    "CURRENT_QUARTER_INDEX": 0,
}

# Scaling factors (PRD Section 2.6)
MICRO = 1_000_000          # units_micro = real units * 1,000,000
MILLI = 1000               # quantity_milli = real quantity * 1000
BPS_SCALE = 10_000         # basis-point scale
QUARTERS_PER_YEAR = 4
ADMIN_FEE_DIVISOR = 40_000  # BPS_SCALE * QUARTERS_PER_YEAR

# Common test values reused across fixtures
TEST_DEFAULTS = {
    "NAV_PER_UNIT_CENTS": 2500,
    "FEE_BPS": 50,
}
