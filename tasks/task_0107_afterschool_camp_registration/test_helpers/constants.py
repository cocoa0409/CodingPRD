"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Sibling discount tiers — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "When N equals 1, no sibling discount applies (the percentage
# is zero). When N equals 2, the per-row percentage is 10 percent. When N
# equals 3, the per-row percentage is 15 percent. When N is 4 or more,
# the per-row percentage is 20 percent."
SIBLING_TIER_N1_PCT: float = 0.00
SIBLING_TIER_N2_PCT: float = 0.10
SIBLING_TIER_N3_PCT: float = 0.15
SIBLING_TIER_N4_PCT: float = 0.20


# ---------------------------------------------------------------------------
# Session field bounds — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "an inclusive age window via age_min and age_max where both
# values lie between 3 and 17 and age_min is at most age_max".
SESSION_AGE_MIN: int = 3
SESSION_AGE_MAX: int = 17

# PRD §3.3: "a weekly_capacity between 1 and 200 setting the per-week
# seat ceiling".
WEEKLY_CAPACITY_MIN: int = 1
WEEKLY_CAPACITY_MAX: int = 200

# PRD §3.3: "a week_count between 1 and 12 giving the number of
# consecutive enrollable weeks".
WEEK_COUNT_MIN: int = 1
WEEK_COUNT_MAX: int = 12


# ---------------------------------------------------------------------------
# Emergency contact bounds — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "an integer priority between 1 and 9 inclusive that
# determines call order".
EMERGENCY_CONTACT_PRIORITY_MIN: int = 1
EMERGENCY_CONTACT_PRIORITY_MAX: int = 9


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10, the minimum is 1, and the maximum
# is 100; the default offset is 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Age calculation — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the integer floor of the calendar-day difference between
# Session.reference_date and Child.date_of_birth divided by 365.2425 days".
DAYS_PER_YEAR: float = 365.2425


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §3.3: a sensible default fee.
    "BASE_WEEKLY_FEE_CENTS": 10_000,
    "WEEKLY_CAPACITY": 10,
    "WEEK_COUNT": 1,
    "RAINY_DAY_POOL_PER_WEEK": 0,
    "AGE_MIN": 5,
    "AGE_MAX": 12,
    "SCHOLARSHIP_TOTAL_CENTS": 5_000,
    # Default child age (in years) that lands inside [5, 12].
    "CHILD_AGE_YEARS": 8,
}


__all__ = [
    "SIBLING_TIER_N1_PCT",
    "SIBLING_TIER_N2_PCT",
    "SIBLING_TIER_N3_PCT",
    "SIBLING_TIER_N4_PCT",
    "SESSION_AGE_MIN",
    "SESSION_AGE_MAX",
    "WEEKLY_CAPACITY_MIN",
    "WEEKLY_CAPACITY_MAX",
    "WEEK_COUNT_MIN",
    "WEEK_COUNT_MAX",
    "EMERGENCY_CONTACT_PRIORITY_MIN",
    "EMERGENCY_CONTACT_PRIORITY_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "DAYS_PER_YEAR",
    "TEST_DEFAULTS",
]
