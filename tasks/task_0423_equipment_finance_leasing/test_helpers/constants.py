"""Domain thresholds — numeric constants from the PRD's calculations and rules.

NON_EXISTENT_UUID is provided by the framework barrel export.
"""

# Pricing-tier credit-score thresholds (PRD §3.2).
PRIME_FLOOR = 720
NEAR_PRIME_FLOOR = 640
APPROVAL_SCORE_FLOOR = 580

# TRAC residual regulatory floor in basis points (PRD §3.4 / §3.6).
TRAC_FLOOR_BPS = 1000

# FMV residual bands (basis points of equipment cost) tiered by term_months (PRD §3.6).
FMV_BAND_SHORT_BPS = 2000   # term <= 24
FMV_BAND_MID_BPS = 1500     # 24 < term <= 48
FMV_BAND_LONG_BPS = 1000    # term > 48
DOLLAR_OUT_RESIDUAL_CENTS = 100  # nominal $1

# Depreciation for property assessed value (PRD §3.8).
ANNUAL_DEPRECIATION_PCT = 0.10
RESIDUAL_FLOOR_PCT = 0.20

# UCC coverage window length in months (PRD §3.7).
UCC_LAPSE_MONTHS = 60

# Serial reuse buffer in days; closed window [D, D+buffer] (PRD §3.5).
SERIAL_REUSE_BUFFER_DAYS = 30

# Common test defaults used by composite fixtures.
TEST_DEFAULTS = {
    "SALES_TAX_RATE_BPS": 825,
    "PROPERTY_TAX_RATE_BPS": 120,
    "HOME_STATE_CODE": "NY",
    "EQUIPMENT_COST_CENTS": 500_000,
    "TERM_MONTHS": 12,
    "MONTHLY_RATE_FACTOR_BPS": 2000,
    "REQUESTED_AMOUNT_CENTS": 1_000_000,
    "CREDIT_SCORE": 760,
}
