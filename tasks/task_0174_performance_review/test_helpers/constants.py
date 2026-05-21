"""Domain thresholds — numeric constants from the PRD.

PRD §3.7 — merit table (annual base percentages):
    OUTSTANDING=9, EXCEEDS=6, MEETS=3, NEEDS_IMPROVEMENT=0, UNSATISFACTORY=0.
    SEMI_ANNUAL halves every cell using integer-division floor.
    Promotion bump (when promotion_to_level is set and rating in
    {OUTSTANDING, EXCEEDS}) is +5% of pinned_base_salary_cents, floored.
PRD §3.7 — equity refresh grant table:
    Levels 1-3:  OUTSTANDING=200, EXCEEDS=100, MEETS=50,  NI=0, UNSAT=0.
    Levels 4-6:  OUTSTANDING=600, EXCEEDS=300, MEETS=150, NI=0, UNSAT=0.
    Levels 7-10: OUTSTANDING=1500, EXCEEDS=800, MEETS=400, NI=0, UNSAT=0.
    Cadence multipliers: ANNUAL=1.0, SEMI_ANNUAL=0.5.
    Promotion bump factor on next-level grant: 0.25 (floored).
PRD §3.5 — bell-curve tolerance: 5 percentage points per bucket.
PRD §3.6 — PIP duration: 60 days for NEEDS_IMPROVEMENT, 30 for UNSATISFACTORY.
PRD §3.3 — feedback floor: peer_feedback_count >= 2 at submit; revision
    cap: revision_count < 3 at return.
PRD §2.3 — pagination defaults.
PRD §3.1 — full_name length range 1..200 inclusive; job_level range 1..10.
PRD §3.3 — Goal.title length 1..500; weight 1..100; scores 1..5.
PRD §3.4 — FeedbackRequest.narrative length 50..5000 at submit.
"""
from __future__ import annotations

from typing import Dict


# ---------------------------------------------------------------------------
# Rating buckets — PRD §3.2, §3.3, §3.5, §3.7
# ---------------------------------------------------------------------------
RATINGS = (
    "OUTSTANDING",
    "EXCEEDS",
    "MEETS",
    "NEEDS_IMPROVEMENT",
    "UNSATISFACTORY",
)

CADENCES = ("ANNUAL", "SEMI_ANNUAL")
RELATIONS = ("PEER", "UPWARD", "DOWNWARD", "CROSS_FUNCTIONAL")
ROLES = ("Admin", "HRBP", "Manager", "Reviewer", "Approver")


# ---------------------------------------------------------------------------
# Merit increase rate table — PRD §3.7 (annual base)
# ---------------------------------------------------------------------------
ANNUAL_MERIT_PCT: Dict[str, int] = {
    "OUTSTANDING": 9,
    "EXCEEDS": 6,
    "MEETS": 3,
    "NEEDS_IMPROVEMENT": 0,
    "UNSATISFACTORY": 0,
}

PROMO_BUMP_PCT: int = 5  # +5 % when promo and rating in {OUTSTANDING, EXCEEDS}


def semi_annual_merit_pct(rating: str) -> int:
    """SEMI_ANNUAL halves every annual cell using integer-division floor.
    PRD §3.7: "every cell of that table is divided by 2 using integer
    division of cents — that is, by taking the floor — so each cycle's
    effective base percentage is half of the annual figure rounded down."
    """
    return ANNUAL_MERIT_PCT[rating] // 2


# ---------------------------------------------------------------------------
# Equity refresh grant table — PRD §3.7
# ---------------------------------------------------------------------------
def equity_base_units(job_level: int, rating: str) -> int:
    """Look up the base grant from PRD §3.7 by level band and rating."""
    if 1 <= job_level <= 3:
        band = {"OUTSTANDING": 200, "EXCEEDS": 100, "MEETS": 50,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0}
    elif 4 <= job_level <= 6:
        band = {"OUTSTANDING": 600, "EXCEEDS": 300, "MEETS": 150,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0}
    elif 7 <= job_level <= 10:
        band = {"OUTSTANDING": 1500, "EXCEEDS": 800, "MEETS": 400,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0}
    else:
        raise ValueError(f"job_level out of supported range 1..10: {job_level}")
    return band[rating]


CADENCE_MULTIPLIER: Dict[str, float] = {
    "ANNUAL": 1.0,
    "SEMI_ANNUAL": 0.5,
}

PROMO_BUMP_FACTOR: float = 0.25


# ---------------------------------------------------------------------------
# Bell-curve tolerance — PRD §3.5
# ---------------------------------------------------------------------------
BELL_CURVE_TOLERANCE_PCT_POINTS: int = 5


# ---------------------------------------------------------------------------
# PIP durations — PRD §3.6
# ---------------------------------------------------------------------------
PIP_DURATION_DAYS: Dict[str, int] = {
    "NEEDS_IMPROVEMENT": 60,
    "UNSATISFACTORY": 30,
}


# ---------------------------------------------------------------------------
# Constraints — PRD §3.3, §3.4
# ---------------------------------------------------------------------------
PEER_FEEDBACK_MIN_FOR_SUBMIT: int = 2
REVISION_CAP_EXCLUSIVE: int = 3
GOAL_WEIGHT_SUM_REQUIRED: int = 100

FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 200
JOB_LEVEL_MIN: int = 1
JOB_LEVEL_MAX: int = 10
GOAL_TITLE_MIN_LEN: int = 1
GOAL_TITLE_MAX_LEN: int = 500
GOAL_WEIGHT_MIN: int = 1
GOAL_WEIGHT_MAX: int = 100
GOAL_SCORE_MIN: int = 1
GOAL_SCORE_MAX: int = 5
FEEDBACK_NARRATIVE_MIN_LEN: int = 50
FEEDBACK_NARRATIVE_MAX_LEN: int = 5000


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
TEST_DEFAULTS: Dict[str, object] = {
    # Standard test base salary: $100,000 = 10_000_000 cents. Chosen so the
    # 9 / 6 / 3 / 5 % computations yield round numbers
    # (900_000 / 600_000 / 300_000 / 500_000 cents).
    "BASE_SALARY_CENTS": 10_000_000,
    "JOB_LEVEL": 4,
    "DEPARTMENT": "Eng",
    "CADENCE": "ANNUAL",
    "BELL_CURVE_TARGET_EVEN": {
        "OUTSTANDING": 20,
        "EXCEEDS": 20,
        "MEETS": 20,
        "NEEDS_IMPROVEMENT": 20,
        "UNSATISFACTORY": 20,
    },
    "REVIEW_WINDOW_START": "2026-01-01T00:00:00.000Z",
    "REVIEW_WINDOW_END": "2026-06-30T23:59:59.000Z",
    "HIRE_DATE": "2024-01-15T00:00:00.000Z",
    # Plenty of slack so fiscal gates do not trip in non-budget tests.
    "MERIT_BUDGET_CENTS": 9_999_999_999,
    "EQUITY_REFRESH_POOL_UNITS": 9_999_999,
    # Calibration commit anchor used to feed /_clock/advance.
    "CLOCK_ANCHOR": "2026-07-01T00:00:00.000Z",
}


__all__ = [
    "RATINGS",
    "CADENCES",
    "RELATIONS",
    "ROLES",
    "ANNUAL_MERIT_PCT",
    "PROMO_BUMP_PCT",
    "semi_annual_merit_pct",
    "equity_base_units",
    "CADENCE_MULTIPLIER",
    "PROMO_BUMP_FACTOR",
    "BELL_CURVE_TOLERANCE_PCT_POINTS",
    "PIP_DURATION_DAYS",
    "PEER_FEEDBACK_MIN_FOR_SUBMIT",
    "REVISION_CAP_EXCLUSIVE",
    "GOAL_WEIGHT_SUM_REQUIRED",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "JOB_LEVEL_MIN",
    "JOB_LEVEL_MAX",
    "GOAL_TITLE_MIN_LEN",
    "GOAL_TITLE_MAX_LEN",
    "GOAL_WEIGHT_MIN",
    "GOAL_WEIGHT_MAX",
    "GOAL_SCORE_MIN",
    "GOAL_SCORE_MAX",
    "FEEDBACK_NARRATIVE_MIN_LEN",
    "FEEDBACK_NARRATIVE_MAX_LEN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
