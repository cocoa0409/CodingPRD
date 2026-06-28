"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Threshold constants named in the PRD workflows.
THRESHOLDS = {
    # A plan defaults once missed installments reach 2 (PRD §3.6).
    "MAX_MISSED_INSTALLMENTS": 2,
    # Lease months accrue in whole 30-day blocks (PRD §3.8).
    "DAYS_PER_MONTH": 30,
    # Basis-point denominator: 10000 bps == 100% (PRD §2.8).
    "BPS_DENOMINATOR": 10000,
    # sales_tax_rate_bps must be in [0, 2000] (PRD §3.1).
    "MAX_SALES_TAX_RATE_BPS": 2000,
    # Pagination bounds (PRD §2.3).
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

# Common values reused across fixtures and tests.
TEST_DEFAULTS = {
    "HOME_STATE": "CA",
    "OUT_OF_STATE": "NY",
    "SALES_TAX_RATE_BPS": 875,          # 8.75%
    "DEFAULT_SPLIT_BPS": 5000,          # artist keeps 50%
    "CLOCK_DEFAULT": "2026-04-01T00:00:00Z",
}
