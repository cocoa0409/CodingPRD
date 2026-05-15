"""Domain thresholds and numeric constants from PRD §3.1–§3.7.

Pulled verbatim from PRD prose:
- OFFER_RESPONSE_HOURS: PRD §3.5 "offer_expires_at to Clock.now plus 168
  hours (the offer-response window of 7 days)".
- WITHDRAW_GRACE_DAYS: PRD §3.6 "the lottery's drawn_at plus the
  withdraw-grace window of 14 days".
- MAX_CHOICES_PER_STUDENT: PRD §3.4 "must not exceed 5".
- POVERTY_BOOST_PER_DECILE: PRD §3.4 "1.0 plus 0.10 times that decile
  count".
- CHOICE_RANK_DECAY: PRD §3.4 "exponent applied to the constant 0.85".
- LOTTERY_WEIGHT_BASE: PRD §3.4 tiered base weight by priority_category.
- PRIORITY_RANK: PRD §3.5 priority bucket ranks for ordering.
- DEFAULT_POVERTY_INDEX_THRESHOLD: PRD §3.1 "defaulting to 0.50".
- WAITLIST_BACKFILL_OFFER_HOURS: PRD §3.7 "Clock.now plus 168 hours".
"""
from __future__ import annotations


# Time windows (PRD §3.5, §3.6, §3.7)
OFFER_RESPONSE_HOURS = 168          # 7 days
WITHDRAW_GRACE_DAYS = 14
WAITLIST_BACKFILL_OFFER_HOURS = 168  # same 168h window per PRD §3.7

# Student limits (PRD §3.4)
MAX_CHOICES_PER_STUDENT = 5
MIN_CHOICE_RANK = 1
MAX_CHOICE_RANK = 5

# Grade level bounds (PRD §3.1 / §3.2)
MIN_GRADE_LEVEL = 0
MAX_GRADE_LEVEL = 12

# District policy defaults (PRD §3.1)
DEFAULT_POVERTY_INDEX_THRESHOLD = 0.50
DEFAULT_ACCEPTS_INTER_DISTRICT_TRANSFERS = False

# Lottery weight numerics (PRD §3.4)
POVERTY_BOOST_PER_DECILE = 0.10
CHOICE_RANK_DECAY = 0.85
LOTTERY_WEIGHT_PRECISION_DECIMALS = 4   # PRD §2.7
LOTTERY_SCORE_PRECISION_DECIMALS = 6    # PRD §2.7

# Tiered base weight by priority_category (PRD §3.4).
LOTTERY_WEIGHT_BASE = {
    "SIBLING_IN_DISTRICT": 4.0,
    "IN_DISTRICT_DISADVANTAGED": 3.0,
    "IN_DISTRICT_STANDARD": 2.0,
    "INTER_DISTRICT_DISADVANTAGED": 1.5,
    "INTER_DISTRICT_STANDARD": 1.0,
}

# Priority category rank order for lottery sort (PRD §3.5).
PRIORITY_RANK = {
    "SIBLING_IN_DISTRICT": 1,
    "IN_DISTRICT_DISADVANTAGED": 2,
    "IN_DISTRICT_STANDARD": 3,
    "INTER_DISTRICT_DISADVANTAGED": 4,
    "INTER_DISTRICT_STANDARD": 5,
}

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Singleton ids (PRD §2.10)
CLOCK_SINGLETON_ID = "clock"

# Defaults useful for setup convenience (not PRD-derived; safe defaults).
TEST_DEFAULTS = {
    "DEFAULT_STATE_CODE": "CA",
    "DEFAULT_DISTRICT_THRESHOLD": 0.50,
    "DEFAULT_SEED": "lottery-seed-test",
}


__all__ = [
    "OFFER_RESPONSE_HOURS",
    "WITHDRAW_GRACE_DAYS",
    "WAITLIST_BACKFILL_OFFER_HOURS",
    "MAX_CHOICES_PER_STUDENT",
    "MIN_CHOICE_RANK",
    "MAX_CHOICE_RANK",
    "MIN_GRADE_LEVEL",
    "MAX_GRADE_LEVEL",
    "DEFAULT_POVERTY_INDEX_THRESHOLD",
    "DEFAULT_ACCEPTS_INTER_DISTRICT_TRANSFERS",
    "POVERTY_BOOST_PER_DECILE",
    "CHOICE_RANK_DECAY",
    "LOTTERY_WEIGHT_PRECISION_DECIMALS",
    "LOTTERY_SCORE_PRECISION_DECIMALS",
    "LOTTERY_WEIGHT_BASE",
    "PRIORITY_RANK",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "CLOCK_SINGLETON_ID",
    "TEST_DEFAULTS",
]
