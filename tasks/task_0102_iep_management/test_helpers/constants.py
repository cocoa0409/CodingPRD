"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# LRE classification boundaries — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "if the percentage is at most 20.00, the classification is
# LRE_A".
LRE_A_UPPER_INCLUSIVE: float = 20.00
# PRD §3.8: "if the percentage is greater than 20.00 and at most 60.00,
# the classification is LRE_B".
LRE_B_UPPER_INCLUSIVE: float = 60.00


# ---------------------------------------------------------------------------
# Goal mastery boundaries — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a score of at least 80.00 yields MASTERED".
MASTERED_THRESHOLD: float = 80.00
# PRD §3.7: "a score of at least 50.00 and strictly less than 80.00
# yields PROGRESSING".
PROGRESSING_THRESHOLD: float = 50.00


# ---------------------------------------------------------------------------
# Triennial cycle — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "if the difference is between zero days and 90 days
# inclusive, triennial_status is DUE_SOON".
DUE_SOON_WINDOW_DAYS: int = 90
# PRD §3.2: "Student.triennial_reevaluation_due_date = finalized_at + 3
# years".
TRIENNIAL_YEARS: int = 3


# ---------------------------------------------------------------------------
# Transition planning — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "requires_transition_plan becomes true on or after the
# calendar day equal to date_of_birth plus 16 calendar years".
TRANSITION_AGE_YEARS: int = 16


# ---------------------------------------------------------------------------
# Compensatory service hours — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "the federal make-up multiplier of 1.5".
MAKEUP_MULTIPLIER: float = 1.5


# ---------------------------------------------------------------------------
# Annual IEP review — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "its scheduled_review_date is set to effective_start_date
# plus 365 days".
IEP_REVIEW_DAYS: int = 365


# ---------------------------------------------------------------------------
# Clock — PRD §2.7
# ---------------------------------------------------------------------------
# PRD §2.7: "When a district is created, its current_date is
# initialised to 2025-01-01T00:00:00.000Z".
INITIAL_DISTRICT_DATE: str = "2025-01-01T00:00:00.000Z"
# PRD §2.7: "an integer by_days in the request body, validated as an
# integer between 1 and 3650 inclusive".
CLOCK_ADVANCE_MIN_DAYS: int = 1
CLOCK_ADVANCE_MAX_DAYS: int = 3650


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — used when a test does not pin a specific value
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # PRD §3.3 example: "1500 minutes for a school operating five
    # 300-minute instructional days".
    "TOTAL_INSTRUCTIONAL_MINUTES": 1500,
    # School-day denominator (instructional + lunch/recess) used in
    # most tests; per PRD §3.8 must be >= instructional minutes.
    "TOTAL_SCHOOL_DAY_MINUTES": 1875,
    # Default beneficiary DOB chosen so the student is below the
    # transition-plan age threshold by default.
    "DEFAULT_DOB": "2014-01-01",
    # Default transition-plan goal: long enough (>= 10 chars per
    # PRD §3.3).
    "POST_SECONDARY_GOAL": (
        "Enroll in a community college within two years of graduation"
    ),
    # A long enough narrative for a progress report; PRD §3.7 requires
    # length 1..2000 inclusive.
    "PROGRESS_NARRATIVE": "Steady progress this reporting period.",
}


__all__ = [
    "LRE_A_UPPER_INCLUSIVE",
    "LRE_B_UPPER_INCLUSIVE",
    "MASTERED_THRESHOLD",
    "PROGRESSING_THRESHOLD",
    "DUE_SOON_WINDOW_DAYS",
    "TRIENNIAL_YEARS",
    "TRANSITION_AGE_YEARS",
    "MAKEUP_MULTIPLIER",
    "IEP_REVIEW_DAYS",
    "INITIAL_DISTRICT_DATE",
    "CLOCK_ADVANCE_MIN_DAYS",
    "CLOCK_ADVANCE_MAX_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
