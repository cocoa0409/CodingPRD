"""Domain thresholds — numeric constants from PRD calculations.

Every constant below is taken verbatim from a §3 narrative or §2.x
convention in the PRD. Tests use these by symbolic name so the boundary
intent is visible.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Segment accrual — PRD §3.3 "Segment accrual formula".
# ---------------------------------------------------------------------------
SEGMENT_FARE_CLASS_MULT = {
    "ECONOMY": 5,
    "BUSINESS": 10,
    "FIRST": 12,
}

SEGMENT_TIER_BONUS_MULT = {
    "BASIC": 1.0,
    "SILVER": 1.25,
    "GOLD": 1.5,
    "PLATINUM": 2.0,
}

SEGMENT_MIN_PER_SEGMENT = 100
SEGMENT_MAX_PER_SEGMENT = 50_000


# ---------------------------------------------------------------------------
# Award price — PRD §3.5.
# ---------------------------------------------------------------------------
AWARD_BASE_RATE_PER_MILE = 5

# Dynamic demand multiplier — PRD §3.5: "a load_factor strictly less than
# 0.50 yields 0.8; a load factor of at least 0.50 but strictly less than
# 0.80 yields 1.0; a load factor of at least 0.80 but strictly less than
# 0.95 yields 1.5; a load factor of 0.95 or above yields 2.0."
DYNAMIC_DEMAND_LOW = 0.8       # load_factor < 0.50
DYNAMIC_DEMAND_MED = 1.0       # 0.50 <= load_factor < 0.80
DYNAMIC_DEMAND_HIGH = 1.5      # 0.80 <= load_factor < 0.95
DYNAMIC_DEMAND_PEAK = 2.0      # 0.95 <= load_factor
DYNAMIC_DEMAND_THRESHOLDS = (0.50, 0.80, 0.95)

CABIN_MULT = {
    "ECONOMY": 1.0,
    "BUSINESS": 2.0,
    "FIRST": 3.5,
}

# Fixed award table — PRD §3.5.
FIXED_AWARD_TABLE = {
    "DOMESTIC": {
        "ECONOMY": 12_500,
        "BUSINESS": 25_000,
        "FIRST": 40_000,
    },
    "INTERNATIONAL": {
        "ECONOMY": 30_000,
        "BUSINESS": 70_000,
        "FIRST": 110_000,
    },
}


# ---------------------------------------------------------------------------
# Tier evaluation thresholds — PRD §3.1.
# ---------------------------------------------------------------------------
SILVER_POINTS_THRESHOLD = 25_000
GOLD_POINTS_THRESHOLD = 50_000
PLATINUM_POINTS_THRESHOLD = 100_000

SILVER_SEGMENTS_THRESHOLD = 25
GOLD_SEGMENTS_THRESHOLD = 50
PLATINUM_SEGMENTS_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Gifting — PRD §3.6.
# ---------------------------------------------------------------------------
GIFT_FEE_RATE = 0.10
GIFT_MIN = 1_000
GIFT_MAX_PER_DAY_PER_SENDER = 50_000


# ---------------------------------------------------------------------------
# Upgrade priority scoring — PRD §3.4.
# ---------------------------------------------------------------------------
TIER_RANK = {
    "BASIC": 0,
    "SILVER": 1,
    "GOLD": 2,
    "PLATINUM": 3,
}
TIER_RANK_WEIGHT = 10_000_000


# ---------------------------------------------------------------------------
# Status match — PRD §3.7.
# ---------------------------------------------------------------------------
STATUS_MATCH_BONUS_POINTS = 5_000
STATUS_MATCH_EXPIRES_MONTHS = 12
STATUS_MATCH_COOLING_OFF_MONTHS = 36


# ---------------------------------------------------------------------------
# Time windows — PRD §2.10.
# ---------------------------------------------------------------------------
AWARD_BOOKING_HOLD_HOURS = 24
ACCRUAL_LIFETIME_MONTHS = 24
COMPANION_CERTIFICATE_VALIDITY_MONTHS = 12


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Convenience defaults for factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "FLIGHT_DISTANCE": 1_000,
    "FLIGHT_BASE_FARE_CENTS": 50_000,    # $500
    "FLIGHT_CAPACITY_ECONOMY": 100,
    "FLIGHT_CAPACITY_BUSINESS": 16,
    "FLIGHT_CAPACITY_FIRST": 4,
}


__all__ = [
    "AWARD_BASE_RATE_PER_MILE",
    "AWARD_BOOKING_HOLD_HOURS",
    "ACCRUAL_LIFETIME_MONTHS",
    "CABIN_MULT",
    "COMPANION_CERTIFICATE_VALIDITY_MONTHS",
    "DYNAMIC_DEMAND_HIGH",
    "DYNAMIC_DEMAND_LOW",
    "DYNAMIC_DEMAND_MED",
    "DYNAMIC_DEMAND_PEAK",
    "DYNAMIC_DEMAND_THRESHOLDS",
    "FIXED_AWARD_TABLE",
    "GIFT_FEE_RATE",
    "GIFT_MAX_PER_DAY_PER_SENDER",
    "GIFT_MIN",
    "GOLD_POINTS_THRESHOLD",
    "GOLD_SEGMENTS_THRESHOLD",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "PLATINUM_POINTS_THRESHOLD",
    "PLATINUM_SEGMENTS_THRESHOLD",
    "SEGMENT_FARE_CLASS_MULT",
    "SEGMENT_MAX_PER_SEGMENT",
    "SEGMENT_MIN_PER_SEGMENT",
    "SEGMENT_TIER_BONUS_MULT",
    "SILVER_POINTS_THRESHOLD",
    "SILVER_SEGMENTS_THRESHOLD",
    "STATUS_MATCH_BONUS_POINTS",
    "STATUS_MATCH_COOLING_OFF_MONTHS",
    "STATUS_MATCH_EXPIRES_MONTHS",
    "TEST_DEFAULTS",
    "TIER_RANK",
    "TIER_RANK_WEIGHT",
]
