"""Domain thresholds — numeric constants drawn from PRD §3.

All values are mirrored verbatim from the PRD prose so that tests
referencing them remain in lockstep with the contract.
"""
from __future__ import annotations


# ---- Pagination (PRD §2.3) ------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---- Overtime fee tiered pricing (PRD §3.5) -------------------------------
FREE_HOURS = 24
TIER1_END_HOURS = 72
TIER2_END_HOURS = 168
TIER1_RATE_CENTS = 100        # $1.00 / hour
TIER2_RATE_CENTS = 200        # $2.00 / hour
TIER3_RATE_CENTS = 400        # $4.00 / hour
FEE_CAP_CENTS = 10000         # $100.00 hard cap


# ---- Capacity warning (PRD §3.2) ------------------------------------------
NEAR_FULL_RATIO = 0.80
PEAK_NEAR_FULL_RATIO = 0.70
FULL_BLOCK_RATIO = 0.95
# Peak hours: half-open windows from 10:00 (inclusive) to 12:00 (exclusive)
# UTC, and from 18:00 (inclusive) to 21:00 (exclusive) UTC.
PEAK_WINDOWS_UTC = [(10, 12), (18, 21)]


# ---- Courier reputation (PRD §3.10) ---------------------------------------
W_SUCCESS = 0.5
W_LOW_WRONG = 0.3
W_LOW_COMPLAINT = 0.2
COMPLAINT_NORM = 5
BLACKLIST_THRESHOLD_RATE = 0.10
BLACKLIST_COMPLAINT_THRESHOLD = 5


# ---- Settlement (PRD §3.11) -----------------------------------------------
PARTNER_SHARE_RATIO = 0.30


# ---- Long-stay / recall / dispose (PRD §3.7) ------------------------------
LONG_STAY_THRESHOLD_HOURS = 168
RECALL_WINDOW_HOURS = 72
DISPOSE_THRESHOLD_HOURS = 336


# ---- Wrong-deposit grace + retry (PRD §3.3 / §3.6) ------------------------
WRONG_DEPOSIT_GRACE_SECONDS = 900
MAX_RETRY = 3


# ---- Pickup-pending hold (PRD §3.4) ---------------------------------------
PICKUP_PENDING_TIMEOUT_SECONDS = 600


# ---- Misc -----------------------------------------------------------------
PICKUP_CODE_LENGTH = 6
SECONDS_PER_HOUR = 3600


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "FREE_HOURS",
    "TIER1_END_HOURS",
    "TIER2_END_HOURS",
    "TIER1_RATE_CENTS",
    "TIER2_RATE_CENTS",
    "TIER3_RATE_CENTS",
    "FEE_CAP_CENTS",
    "NEAR_FULL_RATIO",
    "PEAK_NEAR_FULL_RATIO",
    "FULL_BLOCK_RATIO",
    "PEAK_WINDOWS_UTC",
    "W_SUCCESS",
    "W_LOW_WRONG",
    "W_LOW_COMPLAINT",
    "COMPLAINT_NORM",
    "BLACKLIST_THRESHOLD_RATE",
    "BLACKLIST_COMPLAINT_THRESHOLD",
    "PARTNER_SHARE_RATIO",
    "LONG_STAY_THRESHOLD_HOURS",
    "RECALL_WINDOW_HOURS",
    "DISPOSE_THRESHOLD_HOURS",
    "WRONG_DEPOSIT_GRACE_SECONDS",
    "MAX_RETRY",
    "PICKUP_PENDING_TIMEOUT_SECONDS",
    "PICKUP_CODE_LENGTH",
    "SECONDS_PER_HOUR",
]
