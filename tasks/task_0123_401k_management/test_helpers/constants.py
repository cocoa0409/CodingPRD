"""Domain thresholds and constants from PRD prose.

All monetary values are integer cents. PRD §3.3 fixes the annual
contribution caps; PRD §3.5 fixes the absolute loan cap and the
windowed-outstanding lookback. PRD §3.7 fixes the uniform lifetime
table for RMDs.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Annual contribution caps — PRD §3.3 "Annual limit enforcement"
# ---------------------------------------------------------------------------
EMPLOYEE_ANNUAL_LIMIT_CENTS = 2_350_000   # $23,500
EMPLOYER_ANNUAL_LIMIT_CENTS = 4_600_000   # $46,000


# ---------------------------------------------------------------------------
# Loan caps — PRD §3.5
# ---------------------------------------------------------------------------
ABSOLUTE_LOAN_CAP_CENTS = 5_000_000       # $50,000
LOAN_WINDOW_DAYS = 365                    # PRD §3.5 (365-day lookback)
LOAN_NEXT_DUE_DAYS = 30                   # origination + 30
LOAN_DEFAULT_GRACE_DAYS = 90              # next_due_date + 90 < current_date
LOAN_TERM_MIN_MONTHS = 1
LOAN_TERM_MAX_MONTHS = 60


# ---------------------------------------------------------------------------
# Hardship — PRD §3.6, §2.8
# ---------------------------------------------------------------------------
HARDSHIP_SUSPENSION_DAYS = 180            # deferral_suspended_until = today+180
FREEZE_SUSPENSION_SENTINEL = "9999-12-31"


# ---------------------------------------------------------------------------
# RMD — PRD §3.7 uniform lifetime table
# ---------------------------------------------------------------------------
RMD_DEFAULT_AGE = 73
UNIFORM_LIFETIME_TABLE = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
    79: 21.1,
    80: 20.2,
}


# ---------------------------------------------------------------------------
# Vesting / graded — PRD §2.11
# ---------------------------------------------------------------------------
GRADED_LENGTH = 7
GRADED_TERMINAL_VALUE = 100


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Test defaults — convenient values used by factories/fixtures
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PLAN_NAME": "Test 401(k) Plan",
    "PLAN_YEAR": 2026,
    "ANNUAL_COMPENSATION_CENTS": 6_000_000,   # $60,000
    "ELECTED_DEFERRAL_PCT": 5.0,
    "HIRE_DATE": "2022-01-01",
    "DATE_OF_BIRTH": "1985-06-15",
    "CLIFF_YEARS": 3,
    "GRADED_PERCENTAGES": [0, 0, 20, 40, 60, 80, 100],
    "TIERED_BRACKETS_BASIC": [
        {"employee_deferral_pct_up_to": 3, "match_rate_pct": 50},
        {"employee_deferral_pct_up_to": 6, "match_rate_pct": 25},
    ],
}


__all__ = [
    "EMPLOYEE_ANNUAL_LIMIT_CENTS",
    "EMPLOYER_ANNUAL_LIMIT_CENTS",
    "ABSOLUTE_LOAN_CAP_CENTS",
    "LOAN_WINDOW_DAYS",
    "LOAN_NEXT_DUE_DAYS",
    "LOAN_DEFAULT_GRACE_DAYS",
    "LOAN_TERM_MIN_MONTHS",
    "LOAN_TERM_MAX_MONTHS",
    "HARDSHIP_SUSPENSION_DAYS",
    "FREEZE_SUSPENSION_SENTINEL",
    "RMD_DEFAULT_AGE",
    "UNIFORM_LIFETIME_TABLE",
    "GRADED_LENGTH",
    "GRADED_TERMINAL_VALUE",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
