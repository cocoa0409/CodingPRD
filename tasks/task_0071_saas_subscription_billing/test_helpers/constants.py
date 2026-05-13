"""Domain thresholds — numeric constants from the PRD.

Field names mirror PRD prose exactly. Generic NON_EXISTENT_UUID comes from
the framework.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Late-fee accrual brackets (PRD §3.10).
#  - days_past_due <= 30 : 1.00% (100 bps)
#  - 30 < days_past_due <= 60 : 2.50% (250 bps)
#  - days_past_due > 60 : 5.00% (500 bps)
# ---------------------------------------------------------------------------
LATE_FEE_TIER1_BPS = 100   # PRD §3.10, §3.12: "RATE_BPS_TIER1 of one hundred basis points"
LATE_FEE_TIER2_BPS = 250   # "RATE_BPS_TIER2 of two hundred fifty basis points"
LATE_FEE_TIER3_BPS = 500   # "RATE_BPS_TIER3 of five hundred basis points"

LATE_FEE_DAYS_TIER1 = 30   # inclusive upper bound for tier1
LATE_FEE_DAYS_TIER2 = 60   # inclusive upper bound for tier2


# ---------------------------------------------------------------------------
# Late-arrival window for usage ingestion (PRD §3.7).
# "an event_timestamp earlier than the current cycle_start minus seven days
#  is rejected with ERR_USAGE_TOO_LATE."
# ---------------------------------------------------------------------------
LATE_ARRIVAL_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Suspension-to-termination grace period (PRD §3.12).
# "A tenant that has been SUSPENDED for more than the termination grace
#  period (thirty days) transitions on the next dunning run from SUSPENDED
#  to TERMINATED."
# ---------------------------------------------------------------------------
TERMINATION_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# "The `limit` parameter defaults to 10, has a minimum of 1, and may not
#  exceed 100; the `offset` parameter defaults to 0 and has no upper bound."
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding (PRD §2.8: "round half up to the nearest cent")
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """PRD §2.8: 'The final rounding step on tax computation and on late-fee
    computation uses round half up to the nearest cent.'
    """
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


__all__ = [
    "LATE_FEE_TIER1_BPS", "LATE_FEE_TIER2_BPS", "LATE_FEE_TIER3_BPS",
    "LATE_FEE_DAYS_TIER1", "LATE_FEE_DAYS_TIER2",
    "LATE_ARRIVAL_WINDOW_DAYS",
    "TERMINATION_GRACE_DAYS",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
]
