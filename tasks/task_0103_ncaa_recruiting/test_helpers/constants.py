"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Penalty score constants — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "Severity points are 10 for LEVEL_I, 5 for LEVEL_II, 2 for
# LEVEL_III, and 1 for LEVEL_IV."
SEVERITY_POINTS_LEVEL_I: int = 10
SEVERITY_POINTS_LEVEL_II: int = 5
SEVERITY_POINTS_LEVEL_III: int = 2
SEVERITY_POINTS_LEVEL_IV: int = 1

# PRD §3.7: "a count of zero yields multiplier 1.0; a count of exactly one
# yields 1.5; a count of two or more yields 2.0."
RECID_MULT_FIRST: float = 1.0
RECID_MULT_SECOND: float = 1.5
RECID_MULT_THIRD_PLUS: float = 2.0

# PRD §3.7: "whose created_at falls strictly before this case's created_at
# and on or after this.created_at − 730 days".
PENALTY_WINDOW_DAYS: int = 730


# ---------------------------------------------------------------------------
# Compliance posture thresholds — PRD §2.7, §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "compliance_status is then RED if penalty_points_total is at
# least 20, YELLOW if it is at least 10 and strictly less than 20, and GREEN
# otherwise. Boundaries are inclusive on the lower side: a total of exactly
# 10 lands at YELLOW, and a total of exactly 20 lands at RED."
COMPLIANCE_YELLOW_THRESHOLD: int = 10
COMPLIANCE_RED_THRESHOLD: int = 20


# ---------------------------------------------------------------------------
# NIL FMV multipliers — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "1.20 for ENDORSEMENT, 1.10 for APPEARANCE, 1.00 for
# SOCIAL_MEDIA_POST, 0.90 for AUTOGRAPH_SIGNING, and 1.05 for
# CAMP_INSTRUCTION."
CAT_MULT_ENDORSEMENT: float = 1.20
CAT_MULT_APPEARANCE: float = 1.10
CAT_MULT_SOCIAL_MEDIA_POST: float = 1.00
CAT_MULT_AUTOGRAPH_SIGNING: float = 0.90
CAT_MULT_CAMP_INSTRUCTION: float = 1.05

# PRD §3.5: "0.80 when sponsor_is_booster is true ... and 1.00 otherwise."
BOOSTER_FACTOR_TRUE: float = 0.80
BOOSTER_FACTOR_FALSE: float = 1.00


# ---------------------------------------------------------------------------
# Pay-for-play thresholds — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the ratio of stated_value_cents to the maximum of
# fmv_calculated_cents and 1 is at least 3.0".
PAY_FOR_PLAY_RATIO_THRESHOLD: float = 3.0

# PRD §3.5: "deliverables_hours is at most 1.0".
TOKEN_HOURS_CEILING: float = 1.0

# PRD §3.5: "at least $10,000 expressed as cents (that is, at least
# 1,000,000 in stated_value_cents)".
TOKEN_VALUE_FLOOR_CENTS: int = 1_000_000

# PRD §3.5: "at least $50,000 expressed as cents (that is, at least 5,000,000
# in stated_value_cents)".
INDUCEMENT_VALUE_FLOOR_CENTS: int = 5_000_000


# ---------------------------------------------------------------------------
# Transfer-portal window — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "an AMATEUR athlete receives a 45-day window, an AT_RISK athlete
# receives a 30-day window".
WINDOW_DAYS_AMATEUR: int = 45
WINDOW_DAYS_AT_RISK: int = 30

# PRD §3.4: "The entry sits in ENTERED for 24 hours and then automatically
# transitions to CONTACT_WINDOW when the logical clock reaches entered_at +
# 24 hours."
PORTAL_HOLDING_PERIOD_HOURS: int = 24


# ---------------------------------------------------------------------------
# Appeal window — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "A SUBSTANTIATED case is appealable for 14 days from the
# timestamp of its SUBSTANTIATED transition."
APPEAL_WINDOW_DAYS: int = 14


# ---------------------------------------------------------------------------
# Eligibility — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "core_courses_completed (must be at least 16)".
MIN_CORE_COURSES: int = 16


# ---------------------------------------------------------------------------
# Eligibility-of-transfer thresholds — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4 graduate-transfer rule: "prior_transfers is exactly one and
# years_attended is at least three".
GRAD_TRANSFER_YEARS_ATTENDED: int = 3


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
    # A football program large enough that single-slot tests rarely
    # bump cap.
    "DEFAULT_FOOTBALL_CAP": 85.0,
    "DEFAULT_FOOTBALL_ROSTER": 85,
    "DEFAULT_BASKETBALL_CAP": 13.0,
    "DEFAULT_BASKETBALL_ROSTER": 15,
    # A modest stated value below the inducement floor.
    "DEFAULT_STATED_VALUE_CENTS": 500_000,
    "DEFAULT_DELIVERABLES_HOURS": 10.0,
    "DEFAULT_MARKET_RATE_CPH": 50_000,
}


__all__ = [
    "SEVERITY_POINTS_LEVEL_I",
    "SEVERITY_POINTS_LEVEL_II",
    "SEVERITY_POINTS_LEVEL_III",
    "SEVERITY_POINTS_LEVEL_IV",
    "RECID_MULT_FIRST",
    "RECID_MULT_SECOND",
    "RECID_MULT_THIRD_PLUS",
    "PENALTY_WINDOW_DAYS",
    "COMPLIANCE_YELLOW_THRESHOLD",
    "COMPLIANCE_RED_THRESHOLD",
    "CAT_MULT_ENDORSEMENT",
    "CAT_MULT_APPEARANCE",
    "CAT_MULT_SOCIAL_MEDIA_POST",
    "CAT_MULT_AUTOGRAPH_SIGNING",
    "CAT_MULT_CAMP_INSTRUCTION",
    "BOOSTER_FACTOR_TRUE",
    "BOOSTER_FACTOR_FALSE",
    "PAY_FOR_PLAY_RATIO_THRESHOLD",
    "TOKEN_HOURS_CEILING",
    "TOKEN_VALUE_FLOOR_CENTS",
    "INDUCEMENT_VALUE_FLOOR_CENTS",
    "WINDOW_DAYS_AMATEUR",
    "WINDOW_DAYS_AT_RISK",
    "PORTAL_HOLDING_PERIOD_HOURS",
    "APPEAL_WINDOW_DAYS",
    "MIN_CORE_COURSES",
    "GRAD_TRANSFER_YEARS_ATTENDED",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
