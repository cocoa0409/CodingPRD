"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10, has a minimum of 1, and a maximum of 100"
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Share-factor — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a four-decimal-place share_factor between 0.0001 and 1.0000"
SHARE_FACTOR_MIN: float = 0.0001
SHARE_FACTOR_MAX: float = 1.0000
# PRD §3.1: "The sum of share_factor across every Unit in the association
# MUST equal exactly 1.0000 after any insert or update"
SHARE_FACTOR_SUM_REQUIRED: float = 1.0000


# ---------------------------------------------------------------------------
# Assessment cycle / charge — PRD §3.2, §3.3
# ---------------------------------------------------------------------------
# PRD §3.2: "total_levy_cents MUST be at least 100 cents"
MIN_LEVY_CENTS: int = 100

# PRD §3.3 late-fee constants
# "The per-period fee is the larger of a flat 2,500 cents (twenty-five
# dollars) or the result of multiplying principal_cents by 0.015"
LATE_FEE_FLAT_CENTS: int = 2500
LATE_FEE_PCT_RATE: float = 0.015
# PRD §3.3: "the number of missed periods is one plus the integer number of
# whole 90-day windows elapsed since due_date" (REGULAR cycle)
LATE_FEE_REGULAR_PERIOD_DAYS: int = 90
# PRD §3.3: "For a SPECIAL cycle the period length is thirty days"
LATE_FEE_SPECIAL_PERIOD_DAYS: int = 30


# ---------------------------------------------------------------------------
# Violation fine schedule — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "occurrence 1 is a warning with fine_cents = 0; occurrence 2 is
# a 5,000-cent fine; occurrence 3 is a 10,000-cent fine; and occurrence 4
# or higher is a 20,000-cent fine"
VIOLATION_FINE_SCHEDULE = {
    1: 0,
    2: 5000,
    3: 10000,
    # 4 and higher: 20000
}
VIOLATION_FINE_HIGH_TIER_CENTS: int = 20000

# PRD §3.5: "cure_deadline = opened_at + 14 days"
VIOLATION_CURE_WINDOW_DAYS: int = 14


# ---------------------------------------------------------------------------
# ACC — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "computes deemed_decision_deadline = submitted_at + 30 days"
ACC_DEEMED_DECISION_DAYS: int = 30
# PRD §3.4: "When yes_votes reaches at least 2 ... it advances to APPROVED;
# when no_votes reaches at least 2 ... it advances to DENIED"
ACC_VOTE_THRESHOLD: int = 2


# ---------------------------------------------------------------------------
# Lien — PRD §3.6, §2.8
# ---------------------------------------------------------------------------
# PRD §2.8: "Lien creation demands it be at least 180,000 cents — that is,
# eighteen hundred dollars"
LIEN_OVERDUE_THRESHOLD_CENTS: int = 180000
# PRD §3.6: "at least one AssessmentCharge on that unit has been in OVERDUE
# status for at least sixty days"
LIEN_OVERDUE_AGING_DAYS: int = 60
# PRD §3.6: "the elapsed time between the lien's created_at and the current
# instant MUST be at least 30 days"
LIEN_COOLING_OFF_DAYS: int = 30


# ---------------------------------------------------------------------------
# Board resolutions — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "When yes_votes reaches at least 3 — a majority of the 4-seat
# board — the resolution transitions to PASSED. When no_votes reaches at
# least 2, or when the current instant exceeds the resolution's created_at
# plus 14 days, the resolution transitions to FAILED."
RESOLUTION_PASS_YES_THRESHOLD: int = 3
RESOLUTION_FAIL_NO_THRESHOLD: int = 2
RESOLUTION_DEADLINE_DAYS: int = 14


# ---------------------------------------------------------------------------
# Elections — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "The quorum_pct defaults to 0.40 (forty percent) when omitted
# and otherwise lies in the closed interval from 0.10 to 1.00 inclusive."
DEFAULT_QUORUM_PCT: float = 0.40
MIN_QUORUM_PCT: float = 0.10
MAX_QUORUM_PCT: float = 1.00


# ---------------------------------------------------------------------------
# Reserve study — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "OK when the ratio is at least 0.70, RESTRICTED when the ratio
# is at least 0.30 but strictly less than 0.70, and SPECIAL_ASSESSMENT_
# REQUIRED when the ratio is strictly less than 0.30"
RESERVE_OK_THRESHOLD: float = 0.70
RESERVE_RESTRICTED_THRESHOLD: float = 0.30


# ---------------------------------------------------------------------------
# Member overdue aggregate — PRD §2.8
# ---------------------------------------------------------------------------
# PRD §2.8: "ACC begin-review demands it be exactly zero."
ACC_OVERDUE_REQUIRED: int = 0
# PRD §2.8: "Lien release demands it be exactly zero."
LIEN_RELEASE_OVERDUE_REQUIRED: int = 0


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "unit_address": "100 Test Lane",
    "member_full_name": "Test Member",
    "violation_description": "Unmaintained lawn",
    "acc_description": "Repaint front door",
    "study_year": 2026,
    "regular_levy_cents": 100_000,
    "special_levy_cents": 50_000,
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SHARE_FACTOR_MIN",
    "SHARE_FACTOR_MAX",
    "SHARE_FACTOR_SUM_REQUIRED",
    "MIN_LEVY_CENTS",
    "LATE_FEE_FLAT_CENTS",
    "LATE_FEE_PCT_RATE",
    "LATE_FEE_REGULAR_PERIOD_DAYS",
    "LATE_FEE_SPECIAL_PERIOD_DAYS",
    "VIOLATION_FINE_SCHEDULE",
    "VIOLATION_FINE_HIGH_TIER_CENTS",
    "VIOLATION_CURE_WINDOW_DAYS",
    "ACC_DEEMED_DECISION_DAYS",
    "ACC_VOTE_THRESHOLD",
    "LIEN_OVERDUE_THRESHOLD_CENTS",
    "LIEN_OVERDUE_AGING_DAYS",
    "LIEN_COOLING_OFF_DAYS",
    "RESOLUTION_PASS_YES_THRESHOLD",
    "RESOLUTION_FAIL_NO_THRESHOLD",
    "RESOLUTION_DEADLINE_DAYS",
    "DEFAULT_QUORUM_PCT",
    "MIN_QUORUM_PCT",
    "MAX_QUORUM_PCT",
    "RESERVE_OK_THRESHOLD",
    "RESERVE_RESTRICTED_THRESHOLD",
    "ACC_OVERDUE_REQUIRED",
    "LIEN_RELEASE_OVERDUE_REQUIRED",
    "TEST_DEFAULTS",
]
