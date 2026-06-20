"""Domain thresholds — numeric constants from the Pension DB Administration PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Compensation / IRC limit (PRD §3.3)
COMP_LIMIT_CENTS = 33_000_000  # $330,000 IRC 401(a)(17) annual compensation limit

# Vesting schedule (PRD §3.2)
CLIFF_YEARS = 3
FULL_VEST_YEARS = 7

# Service credit measurement (PRD §3.2)
MEASUREMENT_DATE_CONST = "2025-01-01"

# Benefit formula (PRD §3.4)
ANNUITY_CONVERSION_FACTOR = 12.0

# J&S reduction (PRD §3.4)
BASE_JS_FACTOR = 1.00
SURVIVOR_LOAD = 0.12
AGE_DIFF_LOAD = 0.005
FACTOR_FLOOR = 0.70

# Lump-sum APV (PRD §3.4)
SLA_ANNUITY_FACTOR = 12.5
SEGMENT_FACTOR_65_PLUS = 12.4
SEGMENT_FACTOR_60_64 = 11.9
SEGMENT_FACTOR_55_59 = 10.8
RELATIVE_VALUE_FLOOR = 0.95

# Early retirement (PRD §3.4)
EARLY_RETIREMENT_AGE = 55

# Funding posture thresholds (PRD §2.5)
RESTRICTED_FLOOR = 0.60
OPEN_FLOOR = 0.80

# PBGC premium (PRD §3.7)
FLAT_RATE_PER_HEAD_CENTS = 10_100  # $101 per participant
VARIABLE_RATE = 0.0052  # $52 per $10,000 UVB
VARIABLE_CAP_PER_HEAD_CENTS = 65_200  # $652 per-participant variable-rate cap

# Defaults for plan creation
TEST_DEFAULTS = {
    "FAP_ACCRUAL_RATE": 0.015,
    "CB_PAY_CREDIT_RATE": 0.05,
    "CB_INTEREST_CREDITING_RATE": 0.04,
    "NORMAL_RETIREMENT_AGE": 65,
}
