"""Domain thresholds — numeric constants from PRD §3 calculations.

All monetary values are in integer cents (PRD §2.6).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# API prefix — PRD §1: "The system mounts under the path prefix /housing-voucher."
# ---------------------------------------------------------------------------
API_PREFIX = "/housing-voucher"


# ---------------------------------------------------------------------------
# Deduction allowances — PRD §3.1, §3.9
# ---------------------------------------------------------------------------
DEPENDENT_ALLOWANCE_CENTS = 48_000        # $480 per dependent
ELDERLY_ALLOWANCE_CENTS = 40_000          # $400 once per qualifying household
MEDICAL_THRESHOLD_PCT = 0.03              # 3% of gross income

# Tenant payment floors — PRD §3.7
WELFARE_RENT_CENTS = 0
MINIMUM_RENT_CENTS = 5_000                # $50/month

# Rent burden cap — PRD §3.7 (inclusive)
RENT_BURDEN_CAP_PCT = 0.40

# Rent reasonableness margin — PRD §3.6
REASONABLENESS_MARGIN_PCT = 0.10


# ---------------------------------------------------------------------------
# Time windows — PRD §3.2, §3.5, §3.8, §3.9
# ---------------------------------------------------------------------------
VOUCHER_INITIAL_SEARCH_DAYS = 120         # PRD §3.2
VOUCHER_REISSUE_SEARCH_DAYS = 60          # PRD §3.8
ANNUAL_REVIEW_WINDOW_DAYS = 30            # PRD §3.9
ANNUAL_INSPECTION_GAP_DAYS = 365          # PRD §3.5
DEFICIENT_CURE_WINDOW_DAYS = 14           # PRD §3.9
CURE_DEADLINE_NONLIFETHREATENING_DAYS = 30  # PRD §3.5
CURE_DEADLINE_LIFETHREATENING_HOURS = 24    # PRD §3.5


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# PHA network — PRD §3.2: "the test deployment ships with PHA_001,
# PHA_002, and PHA_003."
# ---------------------------------------------------------------------------
PHA_NETWORK = ("PHA_001", "PHA_002", "PHA_003")
DEFAULT_PHA_ID = "PHA_001"


# ---------------------------------------------------------------------------
# Defaults used by factories — used to anchor test scenarios.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ZONE": "ZONE_A",
    "BEDROOM_COUNT": 2,
    "DEFAULT_GROSS_INCOME_CENTS": 3_000_000,     # $30,000/yr
    "DEFAULT_HOUSEHOLD_SIZE": 3,
    "DEFAULT_DEPENDENTS": 1,
    "DEFAULT_ASKING_RENT_CENTS": 110_000,        # $1,100/mo
    "DEFAULT_UTILITIES_CENTS": 10_000,           # $100/mo
    "DEFAULT_STANDARD_CENTS": 120_000,           # $1,200/mo PS
    "DEFAULT_MOBILITY_CENTS": 132_000,           # 110% of standard
}


__all__ = [
    "API_PREFIX",
    "DEPENDENT_ALLOWANCE_CENTS",
    "ELDERLY_ALLOWANCE_CENTS",
    "MEDICAL_THRESHOLD_PCT",
    "WELFARE_RENT_CENTS",
    "MINIMUM_RENT_CENTS",
    "RENT_BURDEN_CAP_PCT",
    "REASONABLENESS_MARGIN_PCT",
    "VOUCHER_INITIAL_SEARCH_DAYS",
    "VOUCHER_REISSUE_SEARCH_DAYS",
    "ANNUAL_REVIEW_WINDOW_DAYS",
    "ANNUAL_INSPECTION_GAP_DAYS",
    "DEFICIENT_CURE_WINDOW_DAYS",
    "CURE_DEADLINE_NONLIFETHREATENING_DAYS",
    "CURE_DEADLINE_LIFETHREATENING_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "PHA_NETWORK",
    "DEFAULT_PHA_ID",
    "TEST_DEFAULTS",
]
