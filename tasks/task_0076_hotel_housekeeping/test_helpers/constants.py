"""Domain thresholds and constants extracted from the PRD.

Numeric values used in PRD calculations (PRD §3.4, §3.5, §3.8, §3.11,
§3.12) and test defaults that exercise them.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Priority scoring (PRD §3.5)
# ---------------------------------------------------------------------------
# "The base is 50 for CHECK_OUT, 30 for STAYOVER, and 20 for SCHEDULED."
TASK_SOURCE_BASE = {
    "CHECK_OUT": 50,
    "STAYOVER": 30,
    "SCHEDULED": 20,
}
# "The VIP bonus is 30 when the parent room's vip_flag is true and 0 otherwise"
VIP_PRIORITY_BONUS = 30
# "the expedite bonus is 20 when the task's expedite_flag is true"
EXPEDITE_PRIORITY_BONUS = 20
# "the early-check-in bonus is 25 when early_check_in_at is non-null and ...
# the four-hour window"
EARLY_CHECK_IN_PRIORITY_BONUS = 25
EARLY_CHECK_IN_WINDOW_HOURS = 4
# "the sum is multiplied by a synergy multiplier of 1.20"
SYNERGY_MULTIPLIER = 1.20
# "a score of at least 100 yields URGENT, a score below 100 but at least 70
# yields HIGH, and a score below 70 yields NORMAL."
URGENT_THRESHOLD = 100
HIGH_THRESHOLD = 70


# ---------------------------------------------------------------------------
# Estimated duration (PRD §3.4)
# ---------------------------------------------------------------------------
# "Base durations are 25 minutes for STANDARD, 45 minutes for SUITE, and
# 75 minutes for PRESIDENTIAL."
BASE_MINUTES = {
    "STANDARD": 25,
    "SUITE": 45,
    "PRESIDENTIAL": 75,
}
# "Overheads are 15 minutes for a CHECK_OUT cleaning, 0 minutes for a
# STAYOVER, and 10 minutes for a SCHEDULED task."
SOURCE_OVERHEAD = {
    "CHECK_OUT": 15,
    "STAYOVER": 0,
    "SCHEDULED": 10,
}


# ---------------------------------------------------------------------------
# Minibar (PRD §3.11)
# ---------------------------------------------------------------------------
# "the gross amount multiplied by the minibar tax rate of 0.10"
MINIBAR_TAX_RATE = 0.10
# "a strict 72-hour window measured from posted_at. The window is half-open"
MINIBAR_DISPUTE_WINDOW_HOURS = 72


# ---------------------------------------------------------------------------
# Room grace period (PRD §2.11, §3.3)
# ---------------------------------------------------------------------------
# "that threshold is 30 minutes"
INSPECTED_GRACE_MINUTES = 30


# ---------------------------------------------------------------------------
# Inspection sampling (PRD §3.8)
# ---------------------------------------------------------------------------
# "every third submission is sampled"
SAMPLE_EVERY_N = 3


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_MIN = 0


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3_600
MINUTES_PER_DAY = 1_440
MINUTES_PER_HOUR = 60


# ---------------------------------------------------------------------------
# Convenient default inputs used by tests / factories
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ZONE_DEFAULT": "FLOOR_12_NORTH",
    "ZONE_ALT": "FLOOR_8_SOUTH",
    "ROOM_TYPE_STANDARD": "STANDARD",
    "ROOM_TYPE_SUITE": "SUITE",
    "ROOM_TYPE_PRESIDENTIAL": "PRESIDENTIAL",
    "PMS_VACANT": "VACANT",
    "PMS_OCCUPIED": "OCCUPIED",
    "TASK_SOURCE_CHECK_OUT": "CHECK_OUT",
    "TASK_SOURCE_STAYOVER": "STAYOVER",
    "TASK_SOURCE_SCHEDULED": "SCHEDULED",
    "MINIBAR_UNIT_PRICE_CENTS": 500,
    "MINIBAR_PAR_LEVEL": 10,
    "MINIBAR_REPLENISH_THRESHOLD": 2,
    "LINEN_REPLACEMENT_COST_CENTS": 2_000,
    "LINEN_PAR_PER_ROOM": 4,
    "LINEN_SCHEDULED_INTERVAL_DAYS": 3,
}


__all__ = [
    "TASK_SOURCE_BASE",
    "VIP_PRIORITY_BONUS",
    "EXPEDITE_PRIORITY_BONUS",
    "EARLY_CHECK_IN_PRIORITY_BONUS",
    "EARLY_CHECK_IN_WINDOW_HOURS",
    "SYNERGY_MULTIPLIER",
    "URGENT_THRESHOLD",
    "HIGH_THRESHOLD",
    "BASE_MINUTES",
    "SOURCE_OVERHEAD",
    "MINIBAR_TAX_RATE",
    "MINIBAR_DISPUTE_WINDOW_HOURS",
    "INSPECTED_GRACE_MINUTES",
    "SAMPLE_EVERY_N",
    "PAGINATION_LIMIT_DEFAULT",
    "PAGINATION_LIMIT_MIN",
    "PAGINATION_LIMIT_MAX",
    "PAGINATION_OFFSET_MIN",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "MINUTES_PER_DAY",
    "MINUTES_PER_HOUR",
    "TEST_DEFAULTS",
]
