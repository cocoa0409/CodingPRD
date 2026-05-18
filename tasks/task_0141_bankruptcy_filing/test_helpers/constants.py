"""Domain thresholds — numeric constants pulled directly from PRD prose.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# State-median income table — PRD §3.3
# PRD §3.3: "for California a single-person household has a median of
# 6,500,000 cents (sixty-five thousand dollars) and a two-person
# household 8,500,000 cents (eighty-five thousand dollars), for Texas a
# single-person household has a median of 6,000,000 cents (sixty thousand
# dollars) and a two-person household 8,000,000 cents (eighty thousand
# dollars), and for any combination of state_code and household_size not
# enumerated the fallback is 6,000,000 cents for a single-person
# household and 8,000,000 cents for a two-person household."
# ---------------------------------------------------------------------------
STATE_MEDIAN_TABLE: dict = {
    ("CA", 1): 6_500_000,
    ("CA", 2): 8_500_000,
    ("TX", 1): 6_000_000,
    ("TX", 2): 8_000_000,
}
DEFAULT_STATE_MEDIAN_1: int = 6_000_000
DEFAULT_STATE_MEDIAN_2: int = 8_000_000


def state_median_for(state_code: str, household_size: int) -> int:
    """Return the median annualized income (cents) per PRD §3.3 table.

    Falls back to the documented defaults for unenumerated combinations.
    """
    key = (state_code, household_size)
    if key in STATE_MEDIAN_TABLE:
        return STATE_MEDIAN_TABLE[key]
    if household_size == 1:
        return DEFAULT_STATE_MEDIAN_1
    if household_size == 2:
        return DEFAULT_STATE_MEDIAN_2
    # PRD doesn't enumerate 3+, but defaults to the two-person figure for
    # household_size >= 2; only call this from contexts where household_size
    # is 1 or 2.
    return DEFAULT_STATE_MEDIAN_2


# ---------------------------------------------------------------------------
# Means-test calculation — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The required_plan_months is 36 when presumption_of_abuse is
# false and 60 when presumption_of_abuse is true."
REQUIRED_PLAN_MONTHS_WITHOUT_PRESUMPTION: int = 36
REQUIRED_PLAN_MONTHS_WITH_PRESUMPTION: int = 60

# PRD §3.3: divides the six-month income sum by 6.
MEANS_TEST_MONTHS_WINDOW: int = 6


# ---------------------------------------------------------------------------
# Trustee-payment waterfall — PRD §3.10
# ---------------------------------------------------------------------------
# PRD §3.10: "The first bucket takes a 10% administrative fee: 10% of
# the pool, rounded half-up at this step".
ADMIN_FEE_RATE: float = 0.10


# ---------------------------------------------------------------------------
# Schedules — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the ten schedules of personal financial information
# traditionally lettered A through J ... taking exactly one of the ten
# enumerated values A, B, C, D, E, F, G, H, I, or J".
SCHEDULE_TYPES_REQUIRED: list = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


# ---------------------------------------------------------------------------
# 341 meeting — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "The proposed meeting_date must be at least 21 days after
# filing_date".
MEETING_341_MIN_GAP_DAYS: int = 21


# ---------------------------------------------------------------------------
# Dismissal threshold — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "The single precondition is that missed_payment_count must
# be at least 3 — this is the strict three-strikes boundary".
DISMISSAL_MISSED_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Household / state — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "household_size (which must be at least 1 ...)"
MIN_HOUSEHOLD_SIZE: int = 1
# PRD §3.1: "state_code consisting of exactly two uppercase letters".
STATE_CODE_LENGTH: int = 2


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "defaults to 10 when omitted, with a minimum of 1 and a
# maximum of 100; values outside this range are rejected as malformed.
# offset ... defaults to 0".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "STATE_CODE": "TX",
    "HOUSEHOLD_SIZE": 1,
    # A modest income that is BELOW the TX-1 median (60,000 USD), so
    # presumption_of_abuse evaluates to false on default test cases.
    "MONTHLY_INCOME_CENTS": 400_000,  # 4,000 USD / month
    "MONTHLY_EXPENSES_CENTS": 200_000,  # 2,000 USD / month
}


__all__ = [
    "STATE_MEDIAN_TABLE",
    "DEFAULT_STATE_MEDIAN_1",
    "DEFAULT_STATE_MEDIAN_2",
    "state_median_for",
    "REQUIRED_PLAN_MONTHS_WITHOUT_PRESUMPTION",
    "REQUIRED_PLAN_MONTHS_WITH_PRESUMPTION",
    "MEANS_TEST_MONTHS_WINDOW",
    "ADMIN_FEE_RATE",
    "SCHEDULE_TYPES_REQUIRED",
    "MEETING_341_MIN_GAP_DAYS",
    "DISMISSAL_MISSED_THRESHOLD",
    "MIN_HOUSEHOLD_SIZE",
    "STATE_CODE_LENGTH",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
