"""Domain thresholds and numeric constants from the PRD.

These constants encode numeric values the PRD pins to calculations
(commission slicing, posting quotas, candidate rate-limit window,
offer acceptance window, settlement holdback).
"""
from __future__ import annotations


# PRD §3.1 — verification refresh.
REVERIFICATION_DAYS = 365

# PRD §3.1, §3.2 — posting-quota tiers by verification_tier (when VERIFIED).
BASIC_POSTING_QUOTA = 5
PREMIUM_POSTING_QUOTA = 25

# PRD §3.2 — auto-expiry of LIVE postings.
POSTING_LISTED_TTL_DAYS = 30

# PRD §3.4 — candidate anti-spam rate-limit.
RATE_LIMIT_MAX_PER_WINDOW = 5
RATE_LIMIT_WINDOW_SECONDS = 60

# PRD §3.5 — interview-round duration (half-open windows).
INTERVIEW_ROUND_MINUTES = 60

# PRD §3.6 — offer acceptance window.
OFFER_ACCEPTANCE_WINDOW_HOURS = 168  # exactly seven days

# PRD §3.7 — onboarding probation.
PROBATION_DAYS = 90
EARLY_PASS_DECISION_DAYS = 30

# PRD §3.8 — commission calc constants.
BPS_DENOMINATOR = 10_000
FIRST_SLICE_CAP_CENTS = 10_000_000  # 100,000.00 monetary units
REMAINDER_DISCOUNT_FACTOR = 0.5
BONUS_SHARE_FACTOR = 0.25
DEFAULT_CLAWBACK_WINDOW_DAYS = 90
DEFAULT_TAX_WITHHOLDING_PCT_BPS = 1000  # 10%
SETTLEMENT_HOLDBACK_DAYS = 30


TEST_DEFAULTS = {
    "POSTING_TITLE": "Senior Backend Engineer",
    "POSTING_DESCRIPTION": "We are hiring a backend engineer. Competitive compensation.",
    "POSTING_SALARY_MIN_CENTS": 800_000,  # 8000.00
    "POSTING_SALARY_MAX_CENTS": 1_200_000,
    "POSTING_BENEFITS": ["MEAL", "HOUSING"],
    "OFFER_BASE_SALARY_CENTS": 5_000_000,  # 50,000.00
    "OFFER_SIGN_ON_BONUS_CENTS": 0,
}


__all__ = [
    "REVERIFICATION_DAYS",
    "BASIC_POSTING_QUOTA",
    "PREMIUM_POSTING_QUOTA",
    "POSTING_LISTED_TTL_DAYS",
    "RATE_LIMIT_MAX_PER_WINDOW",
    "RATE_LIMIT_WINDOW_SECONDS",
    "INTERVIEW_ROUND_MINUTES",
    "OFFER_ACCEPTANCE_WINDOW_HOURS",
    "PROBATION_DAYS",
    "EARLY_PASS_DECISION_DAYS",
    "BPS_DENOMINATOR",
    "FIRST_SLICE_CAP_CENTS",
    "REMAINDER_DISCOUNT_FACTOR",
    "BONUS_SHARE_FACTOR",
    "DEFAULT_CLAWBACK_WINDOW_DAYS",
    "DEFAULT_TAX_WITHHOLDING_PCT_BPS",
    "SETTLEMENT_HOLDBACK_DAYS",
    "TEST_DEFAULTS",
]
