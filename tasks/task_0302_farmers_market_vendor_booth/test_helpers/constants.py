"""Domain thresholds and pinned policy constants from the PRD calculations.

Numeric constants here back the fee, commission, and ledger calculations
described in PRD 3.4, 3.7, and 3.8.
"""

# Booth size multipliers, expressed in hundredths to keep integer math (PRD 3.4).
SIZE_MULT = {
    "SINGLE": 100,
    "DOUBLE": 180,
    "CORNER": 150,
}

# Basis-point denominator for commission (PRD 2.7 / 3.8).
BPS_DENOMINATOR = 10000

# Standard market policy reused across fixtures and tests.
STANDARD_MARKET = {
    "SEASON_FEE_CENTS": 50000,
    "DAILY_FEE_CENTS": 4000,
    "COMMISSION_BPS": 700,
    "VOUCHER_FACE_VALUE_CENTS": 200,
    "SEASON_START": "2026-06-01",
    "SEASON_END": "2026-09-30",
}

# Pagination defaults (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
