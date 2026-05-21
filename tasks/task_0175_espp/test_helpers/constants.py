"""Domain thresholds — numeric constants from the PRD.

Values mirror PRD §3.1 (plan-config ranges and defaults), §2.7
(precision rules), §2.3 (pagination) and §3.8 (dilution score
normalization constants).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Plan configuration ranges and defaults — PRD §3.1
# ---------------------------------------------------------------------------
PLAN_NAME_MIN_LEN: int = 1
PLAN_NAME_MAX_LEN: int = 120

OFFERING_PERIOD_MONTHS_MIN: int = 6
OFFERING_PERIOD_MONTHS_MAX: int = 24

MAX_CONTRIBUTION_RATE_BP_DEFAULT: int = 1500
MAX_CONTRIBUTION_RATE_BP_CEILING: int = 1500  # 15.00 %

ANNUAL_ACCRUAL_CAP_CENTS_DEFAULT: int = 2_500_000  # $25,000

DISCOUNT_BP_DEFAULT: int = 1500
DISCOUNT_BP_MIN: int = 0
DISCOUNT_BP_MAX: int = 1500

LOOKBACK_ENABLED_DEFAULT: bool = True


# ---------------------------------------------------------------------------
# Precision — PRD §2.7
# ---------------------------------------------------------------------------
BP_DENOM: int = 10_000


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Dilution score normalization — PRD §3.8
# ---------------------------------------------------------------------------
RATE_NORM: int = 1500
CAP_NORM: int = 2_500_000
LOW_RATE_GATE: float = 0.5
W_RATE: float = 0.4
W_CAP: float = 0.3
W_PARTICIPATION: float = 0.3


# ---------------------------------------------------------------------------
# Test defaults — used by fixtures / factories.
# An initial clock that pre-dates every test scenario; tests advance from
# here. Chosen well before any effective_date used in fixtures so plan
# activation passes the "effective_date >= current_time" check at PRD §3.1.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "INITIAL_CLOCK_ISO": "2023-12-01T00:00:00.000Z",
    "PLAN_EFFECTIVE_DATE": "2024-01-01T00:00:00.000Z",
    "GRANT_FMV_CENTS": 1000,         # $10.00
    "PURCHASE_FMV_CENTS": 2000,      # $20.00
    "DEFAULT_RATE_BP": 1500,         # 15 %
    "DEFAULT_GROSS_PAY_CENTS": 100_000,
    "OFFERING_PERIOD_MONTHS": 6,
}


__all__ = [
    "PLAN_NAME_MIN_LEN",
    "PLAN_NAME_MAX_LEN",
    "OFFERING_PERIOD_MONTHS_MIN",
    "OFFERING_PERIOD_MONTHS_MAX",
    "MAX_CONTRIBUTION_RATE_BP_DEFAULT",
    "MAX_CONTRIBUTION_RATE_BP_CEILING",
    "ANNUAL_ACCRUAL_CAP_CENTS_DEFAULT",
    "DISCOUNT_BP_DEFAULT",
    "DISCOUNT_BP_MIN",
    "DISCOUNT_BP_MAX",
    "LOOKBACK_ENABLED_DEFAULT",
    "BP_DENOM",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "RATE_NORM",
    "CAP_NORM",
    "LOW_RATE_GATE",
    "W_RATE",
    "W_CAP",
    "W_PARTICIPATION",
    "TEST_DEFAULTS",
]
