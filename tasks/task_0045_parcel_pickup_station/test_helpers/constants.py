"""Domain thresholds and tuning constants from PRD §3.

Numeric values are the ones stated in PRD prose; tests use these so
boundaries are not duplicated in the suite.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Station defaults (PRD §3.1)
# ---------------------------------------------------------------------------
DEFAULT_FREE_STORAGE_HOURS = 72  # PRD §3.1: 'defaults to 72 hours'
STATION_NAME_MIN_LEN = 1
STATION_NAME_MAX_LEN = 100
STATION_STORAGE_CAPACITY_MIN = 1
STATION_FREE_STORAGE_HOURS_MIN = 1


# ---------------------------------------------------------------------------
# ShelfZone (PRD §3.1)
# ---------------------------------------------------------------------------
SHELF_ZONE_CODE_MIN_LEN = 1
SHELF_ZONE_CODE_MAX_LEN = 16
SHELF_ZONE_ROW_MIN = 1
SHELF_ZONE_COL_MIN = 1


# ---------------------------------------------------------------------------
# Phone (PRD §3.1 staff, §3.2 recipient)
# ---------------------------------------------------------------------------
PHONE_MIN_LEN = 6
PHONE_MAX_LEN = 15


# ---------------------------------------------------------------------------
# Pickup codes (PRD §3.3)
# ---------------------------------------------------------------------------
PICKUP_CODE_LENGTH = 6
PICKUP_CODE_RETRY_LIMIT = 20


# ---------------------------------------------------------------------------
# Storage fee tiers (PRD §3.8)
# ---------------------------------------------------------------------------
TIER1_HOURS = 24       # 'first 24 of those overdue hours'
TIER2_HOURS = 72       # 'next 72 overdue hours (overdue hours 25 through 96)'
TIER1_RATE = 0.50      # CNY per hour
TIER2_RATE = 1.00      # CNY per hour
TIER3_RATE = 2.00      # CNY per hour
SIZE_MULTIPLIER = {
    "S": 1.0,
    "M": 1.0,
    "L": 1.5,
    "XL": 2.0,
}


# ---------------------------------------------------------------------------
# Handover fee per parcel (PRD §3.9)
# ---------------------------------------------------------------------------
HANDOVER_FEE_PER_PARCEL = 0.80


# ---------------------------------------------------------------------------
# Reminder + sweep timing (PRD §3.5, §3.7)
# ---------------------------------------------------------------------------
ESCALATION_HOURS = 24            # T3_ESCALATION threshold beyond deadline
LONG_STAY_HOURS = 168            # shelved_at + 168h triggers AWAITING_RETURN
DISPOSAL_GRACE_HOURS = 240       # long_stay_flagged_at + 240h gates dispose
SLA_MINUTES = 15                 # response_timeliness_score SLA
AUTHORIZATION_MAX_WINDOW_DAYS = 7  # expires_at <= free_storage_deadline + 7 days


# ---------------------------------------------------------------------------
# Quality composite weights + tier mapping (PRD §3.10)
# ---------------------------------------------------------------------------
W_MIS_SHELVING = 0.30
W_LOST_PARCEL = 0.30
W_COMPLAINT = 0.20
W_RESPONSE_TIME = 0.20

# composite -> factor mapping (inclusive lower bound)
COMPOSITE_HIGH_TIER = 0.95   # >= 0.95 -> 1.05
COMPOSITE_MID_TIER = 0.85    # >= 0.85 -> 1.00
COMPOSITE_LOW_TIER = 0.70    # >= 0.70 -> 0.95; else 0.85
FACTOR_HIGH = 1.05
FACTOR_MID = 1.00
FACTOR_LOW = 0.95
FACTOR_PENALTY = 0.85


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_FREE_STORAGE_HOURS",
    "STATION_NAME_MIN_LEN",
    "STATION_NAME_MAX_LEN",
    "STATION_STORAGE_CAPACITY_MIN",
    "STATION_FREE_STORAGE_HOURS_MIN",
    "SHELF_ZONE_CODE_MIN_LEN",
    "SHELF_ZONE_CODE_MAX_LEN",
    "SHELF_ZONE_ROW_MIN",
    "SHELF_ZONE_COL_MIN",
    "PHONE_MIN_LEN",
    "PHONE_MAX_LEN",
    "PICKUP_CODE_LENGTH",
    "PICKUP_CODE_RETRY_LIMIT",
    "TIER1_HOURS",
    "TIER2_HOURS",
    "TIER1_RATE",
    "TIER2_RATE",
    "TIER3_RATE",
    "SIZE_MULTIPLIER",
    "HANDOVER_FEE_PER_PARCEL",
    "ESCALATION_HOURS",
    "LONG_STAY_HOURS",
    "DISPOSAL_GRACE_HOURS",
    "SLA_MINUTES",
    "AUTHORIZATION_MAX_WINDOW_DAYS",
    "W_MIS_SHELVING",
    "W_LOST_PARCEL",
    "W_COMPLAINT",
    "W_RESPONSE_TIME",
    "COMPOSITE_HIGH_TIER",
    "COMPOSITE_MID_TIER",
    "COMPOSITE_LOW_TIER",
    "FACTOR_HIGH",
    "FACTOR_MID",
    "FACTOR_LOW",
    "FACTOR_PENALTY",
]
