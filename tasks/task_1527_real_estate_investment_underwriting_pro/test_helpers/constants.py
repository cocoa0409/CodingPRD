"""Domain thresholds and canonical fixture numbers (PRD §2.5, §2.9, §3)."""

# Fixed arithmetic constants (PRD §2.5: basis-point and month conventions).
BPS_DENOM = 10000
MONTHS_PER_YEAR = 12

# IC quorum: "If the count of `YES` votes is at least 2 (the quorum constant
# `IC_QUORUM_YES`) ..." (PRD §3.8).
IC_QUORUM_YES = 2

# Waterfall equity split: "LP equity is the deal's `target_purchase_price_cents`
# multiplied by 0.90; GP equity is the remainder." (PRD §3.6).
LP_EQUITY_SHARE = 0.90

# Logical clock startup default (PRD §2.9).
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

# Canonical data-room numbers used by the NOI / debt-sizing / waterfall tests.
CANONICAL = {
    "PRICE_CENTS": 1_000_000_000,
    "UNITS": 100,
    "RENTABLE_SQFT": 100_000,
    "YEAR_BUILT": 2005,
    "PERIOD_MONTH": "2026-06",
    "OCCUPIED_UNITS": 92,
    "TOTAL_UNITS": 100,
    "GPR_CENTS": 10_000_000,
    "COLLECTED_CENTS": 9_200_000,
    "CONCESSIONS_CENTS": 200_000,
    "EXPENSE_YEAR": 2025,
    # TAXES + INSURANCE + UTILITIES + REPAIRS + MANAGEMENT
    "EXPENSE_ROWS": [
        ("TAXES", 12_000_000),
        ("INSURANCE", 3_000_000),
        ("UTILITIES", 4_800_000),
        ("REPAIRS", 1_800_000),
        ("MANAGEMENT", 3_600_000),
    ],
    "ASSUMPTION": {
        "label": "Base",
        "market_rent_growth_yr1_bps": 250,
        "market_rent_growth_steady_bps": 300,
        "expense_growth_bps": 200,
        "exit_cap_rate_bps": 550,
        "hold_period_years": 5,
        "capex_per_unit_cents": 500_000,
        "lease_up_months": 6,
    },
}

TEST_DEFAULTS = {
    "DEAL_PRICE_CENTS": 100_000_000,
    "ASSUMPTION": {
        "label": "Base",
        "market_rent_growth_yr1_bps": 200,
        "market_rent_growth_steady_bps": 200,
        "expense_growth_bps": 200,
        "exit_cap_rate_bps": 600,
        "hold_period_years": 5,
        "capex_per_unit_cents": 100_000,
        "lease_up_months": 0,
    },
}
