"""Domain thresholds — numeric constants from PRD calculations.

All monetary values are integer cents per PRD §2.10:
"All monetary fields in the system are stored as integer cents."
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Interview booking — PRD §3.4
#   "a 15-minute buffer applied to both sides of each existing interval"
# ---------------------------------------------------------------------------
INTERVIEW_BUFFER_MINUTES: int = 15


# ---------------------------------------------------------------------------
# Recruiter open-requisition cap — PRD §3.2
#   "a `Recruiter` may own at most 5 requisitions for which `posted_at`
#    is non-null and `closed_at` is null"
# ---------------------------------------------------------------------------
MAX_OPEN_REQUISITIONS_PER_RECRUITER: int = 5


# ---------------------------------------------------------------------------
# Referral bonus — PRD §3.6
#   Seniority schedule (cents):
#     JUNIOR yields $1,500.00 ($150,000 cents)
#     MID yields $2,500.00 ($250,000 cents)
#     SENIOR yields $5,000.00 ($500,000 cents)
#     STAFF yields $7,500.00 ($750,000 cents)
#     PRINCIPAL yields $10,000.00 ($1,000,000 cents)
# ---------------------------------------------------------------------------
REFERRAL_BONUS_BASE_CENTS: dict = {
    "JUNIOR": 150_000,
    "MID": 250_000,
    "SENIOR": 500_000,
    "STAFF": 750_000,
    "PRINCIPAL": 1_000_000,
}

# PRD §3.6: "the uplift starts as 50% of the base amount in cents,
# rounded half up."
REFERRAL_UPLIFT_RATE: float = 0.50

# PRD §3.6: "the cap is $2,000.00 ($200,000 cents) when the requisition
# is NOT tied to a `target_diversity_goal_id`, and $4,000.00 ($400,000
# cents) when it IS tied to one."
REFERRAL_UPLIFT_CAP_DEFAULT_CENTS: int = 200_000
REFERRAL_UPLIFT_CAP_GOAL_CENTS: int = 400_000

# PRD §3.6: "The bonus's `payable_at` is set to the moment of the hire
# plus a 90-day waiting period."
REFERRAL_WAITING_DAYS: int = 90


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test default values used by factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # Anchor instant for all date arithmetic in tests. Anything before
    # this is "the past"; anything after is "the future" for /extend /
    # /accept time gates.
    "INITIAL_CLOCK_ISO": "2026-05-20T08:00:00.000Z",
    "DEFAULT_DEPARTMENT_CODE": "ENG",
    "DEFAULT_JOB_TITLE": "Software Engineer",
    "DEFAULT_RECRUITER_FULL_NAME": "Test Recruiter",
    "DEFAULT_HM_FULL_NAME": "Test Hiring Manager",
    "DEFAULT_INTERVIEWER_FULL_NAME": "Test Interviewer",
    "DEFAULT_CANDIDATE_FULL_NAME": "Test Candidate",
    # Big enough manager budget so /approve does not run into
    # ERR_MANAGER_BUDGET_EXCEEDED unless the test specifically constructs
    # the boundary.
    "DEFAULT_HM_BUDGET_CENTS": 1_000_000_000,
    # Big enough requisition budget so the per-offer cap is not the
    # binding constraint unless the test sets up that boundary.
    "DEFAULT_REQ_BUDGET_CENTS": 100_000_000,
}


__all__ = [
    "INTERVIEW_BUFFER_MINUTES",
    "MAX_OPEN_REQUISITIONS_PER_RECRUITER",
    "REFERRAL_BONUS_BASE_CENTS",
    "REFERRAL_UPLIFT_RATE",
    "REFERRAL_UPLIFT_CAP_DEFAULT_CENTS",
    "REFERRAL_UPLIFT_CAP_GOAL_CENTS",
    "REFERRAL_WAITING_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
