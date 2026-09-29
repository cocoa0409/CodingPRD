"""
Business constants for the Student Loan Repayment Match Benefit API.

Every literal here is a value the PRD declares (statutory ceilings, the shared
tier ladder, the vesting schedule, the ACP multiples, the leave defaults, and
the logical clock's pinned starting instant).
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Plan-year defaults (PRD §2.6, §3.1)
# ---------------------------------------------------------------------------

DEFAULT_COMPENSATION_CAP_CENTS = 34_500_000
DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS = 2_300_000
DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS = 15_500_000

DEFAULT_TIER1_PCT = 0.03
DEFAULT_TIER1_MATCH_RATE = 1.00
DEFAULT_TIER2_PCT = 0.02
DEFAULT_TIER2_MATCH_RATE = 0.50

DEFAULT_NONDISCRIMINATION_TEST_METHOD = "CURRENT_YEAR"
DEFAULT_PRIOR_YEAR_NHCE_ACP = 0.0000
DEFAULT_UNPAID_LEAVE_DAY_CAP = 180
DEFAULT_LEAVE_MERGE_BUFFER_DAYS = 14

# ---------------------------------------------------------------------------
# ACP nondiscrimination testing (PRD §3.9)
# ---------------------------------------------------------------------------

ACP_BASIC_MULTIPLE = 1.25
ACP_ALTERNATE_MULTIPLE = 2
ACP_ALTERNATE_SPREAD = 0.02
ACP_RATIO_DECIMAL_PLACES = 4

# ---------------------------------------------------------------------------
# Vesting schedule (PRD §3.7)
# ---------------------------------------------------------------------------

VESTING_CLIFF_MONTHS = 24
VESTING_FULL_MONTHS = 60

# (lower bound in completed months, vested_pct)
VESTING_LADDER = [
    (0, 0.00),
    (24, 0.40),
    (36, 0.60),
    (48, 0.80),
    (60, 1.00),
]

# ---------------------------------------------------------------------------
# Canonical plan-year window used by the test suite
# ---------------------------------------------------------------------------

PLAN_YEAR_2026 = 2026
PLAN_YEAR_2026_START = "2026-01-01T00:00:00Z"
PLAN_YEAR_2026_END = "2026-12-31T23:59:59Z"
CERT_WINDOW_2026_OPEN = "2026-01-01T00:00:00Z"
CERT_DEADLINE_2026 = "2026-12-31T23:59:59Z"

# ---------------------------------------------------------------------------
# Canonical payroll-period calendar (monthly periods inside plan year 2026)
# ---------------------------------------------------------------------------

MONTH_END_DAY = {
    1: 31,
    2: 28,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


def payroll_period_window(period_number: int, year: int = 2026) -> dict:
    """Return start/end/pay dates for the Nth monthly payroll period of a year."""
    month = period_number
    end_day = MONTH_END_DAY[month]
    start = f"{year}-{month:02d}-01T00:00:00Z"
    end = f"{year}-{month:02d}-{end_day:02d}T23:59:59Z"
    if month == 12:
        pay = f"{year + 1}-01-05T00:00:00Z"
    else:
        pay = f"{year}-{month + 1:02d}-05T00:00:00Z"
    return {"start_date": start, "end_date": end, "pay_date": pay}


# ---------------------------------------------------------------------------
# Canonical monetary fixtures used throughout the suite
# ---------------------------------------------------------------------------

STANDARD_PERIOD_COMPENSATION_CENTS = 1_000_000
STANDARD_PERIOD_DEFERRAL_CENTS = 20_000

# With 1,000,000 cents of counted compensation and a 20,000-cent deferral the
# shared ladder leaves this much room for certified loan payments.
STANDARD_TIER1_FREE_CENTS = 10_000
STANDARD_TIER2_FREE_CENTS = 20_000

STANDARD_CERTIFIED_PAYMENT_CENTS = 30_000
STANDARD_MIRROR_MATCH_CENTS = 20_000

NHCE_PRIOR_COMPENSATION_CENTS = 6_000_000
HCE_PRIOR_COMPENSATION_CENTS = 20_000_000

FULLY_VESTED_SERVICE_MONTHS = 72
UNVESTED_SERVICE_MONTHS = 12

# ---------------------------------------------------------------------------
# Canonical opaque user ids (PRD §2.1 opaque-identity roles)
# ---------------------------------------------------------------------------

ACCEPTING_ADMIN_USER_ID = "admin-1"
INDEPENDENT_AUDITOR_USER_ID = "auditor-9"
