"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Calculation constants.
AGE_CAP = 90               # ages above 90 use the age-90 factor row
MIN_AGE = 62               # regulatory age floor at origination
BPS_DIVISOR = 10000
MONTHS_PER_YEAR = 12
PARTIAL_FACTOR_DENOM = 2   # PARTIALLY_FUNDED divides the horizon by 2
TENURE_TERMINAL_AGE = 100  # HUD pays a tenure loan until borrower reaches age 100
NON_RECOURSE_FACTOR_PCT = 95  # 95% of appraised value cap

# Shared baseline figures used across the difficulty-design "LOC base loan"
# (lender hud_lending_limit 80000000, PLF age 75 @ 500bps = 523000,
#  appraised 30000000, initial_financed_costs 1000000).
DEFAULT_HUD_LENDING_LIMIT_CENTS = 80000000
DEFAULT_APPRAISED_VALUE_CENTS = 30000000
DEFAULT_EXPECTED_RATE_BPS = 500
DEFAULT_FACTOR_MICROS = 523000
DEFAULT_INITIAL_FINANCED_COSTS_CENTS = 1000000
DEFAULT_BORROWER_BIRTHDATE = "1948-06-01"   # age 75 at 2024-01-01
DEFAULT_CLOCK_ISO = "2024-01-01T00:00:00.000Z"
DEFAULT_PLF_AGE = 75

# Pre-computed expected values for the LOC base loan after origination.
LOC_BASE_GROSS_PRINCIPAL_LIMIT_CENTS = 15690000
LOC_BASE_NET_PRINCIPAL_LIMIT_CENTS = 14690000
LOC_BASE_AVAILABLE_LINE_CENTS = 14690000
LOC_BASE_PRINCIPAL_BALANCE_CENTS = 1000000
