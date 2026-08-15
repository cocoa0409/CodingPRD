"""Domain thresholds and numeric constants pinned by the PRD.

All money is integer cents; all rates/margins/haircuts are integer basis
points. The logical clock defaults to exactly 2026-08-01T00:00:00Z at
server startup.
"""

THRESHOLDS = {
    # Margin requirement branches (PRD §2.11)
    "MARGIN_BPS_CASH": 10200,
    "MARGIN_BPS_SECURITIES": 10500,
    # Per-asset-class collateral haircuts (PRD §2.11)
    "HAIRCUT_BPS_GOV_BOND": 200,
    "HAIRCUT_BPS_CORP_BOND": 600,
    "HAIRCUT_BPS_EQUITY": 1000,
    # Utilization soft cap — booking at >= 9000bps is blocked (PRD §2.9)
    "SOFT_CAP_BPS": 9000,
    # Fail-fee rate (PRD §3.7)
    "FAIL_FEE_BPS": 100,
    # Day-count basis for fee/rebate/reinvest accruals (PRD §2.5)
    "DAY_COUNT_BASIS": 360,
}

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "PRICE_CENTS": 1000,
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "LARGE_CREDIT_LIMIT_CENTS": 2_000_000_000,
    "MIN_FEE_BPS": 25,
    "REBATE_BPS_ZERO": 0,
    "REBATE_BPS_TYPICAL": 150,
    "STATED_YIELD_BPS": 360,
}
