"""Domain thresholds — numeric constants from PRD calculations.

These are pinned directly from PRD prose. Computed-field constants
(e.g., FMLA bucket size, PFL cap) are also re-exported so test bodies
can reference them by name rather than magic-number them.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Eligibility thresholds — PRD §3.2
# ---------------------------------------------------------------------------
MIN_MONTHS_SERVICE: int = 12
MIN_HOURS_TRAILING_12MO: int = 1250
MIN_WORKSITE_HEADCOUNT_75MI: int = 50


# ---------------------------------------------------------------------------
# FMLA quota — PRD §3.7
# ---------------------------------------------------------------------------
FMLA_ENTITLEMENT_HOURS: int = 480
WORKWEEK_HOURS: int = 40


# ---------------------------------------------------------------------------
# PFL weekly benefit — PRD §3.8
# ---------------------------------------------------------------------------
WEEKS_PER_YEAR: int = 52
MONTHS_PER_YEAR: int = 12
PFL_REPLACEMENT_RATIO: float = 0.60
PFL_WEEKLY_CAP_CENTS: int = 162_900  # $1,629.00
PFL_WEEKS_MIN: int = 1
PFL_WEEKS_MAX: int = 8


# ---------------------------------------------------------------------------
# Hours-used per LeaveInstance — PRD §3.4
# ---------------------------------------------------------------------------
INSTANCE_HOURS_MIN: int = 1
INSTANCE_HOURS_MAX: int = 24


# ---------------------------------------------------------------------------
# Certification deadlines — PRD §3.3, §3.5
# ---------------------------------------------------------------------------
CERT_DEADLINE_DAYS: int = 15
CERT_CURE_DAYS: int = 7


# ---------------------------------------------------------------------------
# Benefit invoice ageing — PRD §3.9
# ---------------------------------------------------------------------------
INVOICE_GRACE_DAYS: int = 30
INVOICE_FORFEIT_DAYS: int = 45


# ---------------------------------------------------------------------------
# Job restoration score — PRD §3.10
# ---------------------------------------------------------------------------
JOB_RESTORATION_FLOOR: int = 50
JOB_RESTORATION_BASE: int = 100
JOB_RESTORATION_MAX: int = 100
CERT_INSUFFICIENT_MULTIPLIER: float = 0.50
INVOICE_FORFEIT_MULTIPLIER: float = 0.00
INVOICE_GRACE_MULTIPLIER: float = 0.75
TENURE_BONUS_MULTIPLIER: float = 1.10
TENURE_BONUS_HOURS_THRESHOLD: int = 2000


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when no override is given.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "EMPLOYER_LEGAL_NAME": "Acme Corp",
    "WORKSITE_ADDRESS": "1 Test Plaza",
    "WORKSITE_HEADCOUNT": 80,
    "EMPLOYEE_FULL_NAME": "Test Employee",
    "EMPLOYEE_HIRE_DATE": "2023-01-01",
    "EMPLOYEE_HOURS_TRAILING_12MO": 2080,
    "EMPLOYEE_MONTHLY_WAGE_CENTS": 500_000,
    "BENEFIT_PREMIUM_SHARE_CENTS": 30_000,
    # Clock anchors used by fixtures — well past the hire date so
    # 12-month tenure is satisfied by default.
    "INITIAL_CLOCK_ISO": "2026-03-01T00:00:00.000Z",
}


__all__ = [
    # Eligibility
    "MIN_MONTHS_SERVICE",
    "MIN_HOURS_TRAILING_12MO",
    "MIN_WORKSITE_HEADCOUNT_75MI",
    # Quota
    "FMLA_ENTITLEMENT_HOURS",
    "WORKWEEK_HOURS",
    # PFL
    "WEEKS_PER_YEAR",
    "MONTHS_PER_YEAR",
    "PFL_REPLACEMENT_RATIO",
    "PFL_WEEKLY_CAP_CENTS",
    "PFL_WEEKS_MIN",
    "PFL_WEEKS_MAX",
    # Instance
    "INSTANCE_HOURS_MIN",
    "INSTANCE_HOURS_MAX",
    # Cert deadlines
    "CERT_DEADLINE_DAYS",
    "CERT_CURE_DAYS",
    # Invoice ageing
    "INVOICE_GRACE_DAYS",
    "INVOICE_FORFEIT_DAYS",
    # Job restoration
    "JOB_RESTORATION_FLOOR",
    "JOB_RESTORATION_BASE",
    "JOB_RESTORATION_MAX",
    "CERT_INSUFFICIENT_MULTIPLIER",
    "INVOICE_FORFEIT_MULTIPLIER",
    "INVOICE_GRACE_MULTIPLIER",
    "TENURE_BONUS_MULTIPLIER",
    "TENURE_BONUS_HOURS_THRESHOLD",
    # Pagination
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    # Defaults
    "TEST_DEFAULTS",
]
