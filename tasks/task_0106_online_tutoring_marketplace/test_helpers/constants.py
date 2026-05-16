"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Tutor rate bounds — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "an hourly_rate_cents between 1000 and 50000 (i.e. $10/hr
# through $500/hr)".
HOURLY_RATE_MIN_CENTS: int = 1000
HOURLY_RATE_MAX_CENTS: int = 50_000


# ---------------------------------------------------------------------------
# Session window — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "start_at must be at least 60 minutes ahead of the current
# clock (the minimum-lead-time rule)".
MIN_LEAD_MINUTES: int = 60

# PRD §3.4: "the scheduled duration must be a positive whole number of
# minutes no greater than 240 (a four-hour cap)".
MAX_SESSION_MINUTES: int = 240


# ---------------------------------------------------------------------------
# Multi-hour discount tiers — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "if scheduled minutes is at least 180, the raw amount is
# multiplied by 0.90 (a 10% discount); else if scheduled minutes is at
# least 120, the raw amount is multiplied by 0.95 (a 5% discount)".
DISCOUNT_TIER_180_MIN: int = 180
DISCOUNT_TIER_180_RATE: float = 0.90
DISCOUNT_TIER_120_MIN: int = 120
DISCOUNT_TIER_120_RATE: float = 0.95


# ---------------------------------------------------------------------------
# Commission tiers — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "if the tutor's lifetime_completed_sessions is at least 100,
# the commission rate is 0.10 (10%); else if it is at least 20, the
# commission rate is 0.15 (15%); otherwise 0.20 (20%)".
COMMISSION_TIER_100_MIN: int = 100
COMMISSION_TIER_100_RATE: float = 0.10
COMMISSION_TIER_20_MIN: int = 20
COMMISSION_TIER_20_RATE: float = 0.15
COMMISSION_TIER_0_RATE: float = 0.20


# ---------------------------------------------------------------------------
# Cancellation fee tiers — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "If hours-of-notice is at least 24, the fee is 0 (a free
# cancel). If hours-of-notice is less than 24 but at least 2, the fee is
# 25% of charged_amount_cents, rounded half-up. If hours-of-notice is
# less than 2, the fee is 50% of charged_amount_cents, rounded half-up."
FREE_NOTICE_HOURS: float = 24.0
LATE_NOTICE_HOURS: float = 2.0
LATE_FEE_RATE: float = 0.25
VERY_LATE_FEE_RATE: float = 0.50


# ---------------------------------------------------------------------------
# Settlement hold + dispute timers — PRD §3.6, §3.7
# ---------------------------------------------------------------------------
# PRD §3.6: "it cannot pay out to the tutor until 72 hours of wall-clock
# time have elapsed since end_at".
SETTLEMENT_HOLD_HOURS: int = 72

# PRD §3.7: "The dispute must be opened within 7 days of the session's
# end_at".
DISPUTE_OPEN_WINDOW_DAYS: int = 7

# PRD §3.7: "the elapsed time since the dispute's created_at is at least
# 14 days".
DISPUTE_ESCALATE_TIMER_DAYS: int = 14

# PRD §3.7: "The counter step is rejected with ERR_INVALID_STATE once
# round_count has already reached 3."
MAX_DISPUTE_ROUNDS: int = 3


# ---------------------------------------------------------------------------
# Parental capacity — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "A parent may manage at most 10 children".
MAX_CHILDREN_PER_PARENT: int = 10


# ---------------------------------------------------------------------------
# Completion early-finish buffer — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the reported adjusted_minutes is at least the scheduled
# minutes minus 10 (allowing a tutor to wrap up to 10 minutes early)".
COMPLETION_EARLY_BUFFER_MIN: int = 10


# ---------------------------------------------------------------------------
# Critical credential types — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "The two critical credential types for verification are
# GOVERNMENT_ID and BACKGROUND_CHECK".
CRITICAL_CREDENTIAL_TYPES = frozenset({"GOVERNMENT_ID", "BACKGROUND_CHECK"})


# ---------------------------------------------------------------------------
# String length bounds — PRD §3.1, §3.3
# ---------------------------------------------------------------------------
# PRD §3.1: display_name "1 to 80 characters".
DISPLAY_NAME_MIN_LEN: int = 1
DISPLAY_NAME_MAX_LEN: int = 80


# ---------------------------------------------------------------------------
# Subject code constraint — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "must match the regular expression of an uppercase letter
# followed by 2 to 29 characters from the set of uppercase letters,
# digits, and underscores; total length 3 to 30 characters".
SUBJECT_CODE_MIN_LEN: int = 3
SUBJECT_CODE_MAX_LEN: int = 30


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Time arithmetic
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE: int = 60
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86_400


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 6000,        # $60/hr
    "TRIAL_RATE_CENTS": 4000,         # $40/hr
    "DEFAULT_SUBJECT": "MATH_ALGEBRA",
    "DEFAULT_PROFICIENCY": "INTERMEDIATE",
}


__all__ = [
    "HOURLY_RATE_MIN_CENTS",
    "HOURLY_RATE_MAX_CENTS",
    "MIN_LEAD_MINUTES",
    "MAX_SESSION_MINUTES",
    "DISCOUNT_TIER_180_MIN",
    "DISCOUNT_TIER_180_RATE",
    "DISCOUNT_TIER_120_MIN",
    "DISCOUNT_TIER_120_RATE",
    "COMMISSION_TIER_100_MIN",
    "COMMISSION_TIER_100_RATE",
    "COMMISSION_TIER_20_MIN",
    "COMMISSION_TIER_20_RATE",
    "COMMISSION_TIER_0_RATE",
    "FREE_NOTICE_HOURS",
    "LATE_NOTICE_HOURS",
    "LATE_FEE_RATE",
    "VERY_LATE_FEE_RATE",
    "SETTLEMENT_HOLD_HOURS",
    "DISPUTE_OPEN_WINDOW_DAYS",
    "DISPUTE_ESCALATE_TIMER_DAYS",
    "MAX_DISPUTE_ROUNDS",
    "MAX_CHILDREN_PER_PARENT",
    "COMPLETION_EARLY_BUFFER_MIN",
    "CRITICAL_CREDENTIAL_TYPES",
    "DISPLAY_NAME_MIN_LEN",
    "DISPLAY_NAME_MAX_LEN",
    "SUBJECT_CODE_MIN_LEN",
    "SUBJECT_CODE_MAX_LEN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
]
