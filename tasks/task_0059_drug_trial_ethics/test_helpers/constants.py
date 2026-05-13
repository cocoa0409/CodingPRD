"""Domain thresholds and numeric constants from the PRD.

Names mirror the constants pinned in PRD §2.9, §3.5, §3.6, §3.7.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Quorum constants (PRD §2.9)
# ---------------------------------------------------------------------------
QUORUM_PERCENT = 67          # PRD §2.9: 'multiplied by 67 percent'
QUORUM_MIN_ABSOLUTE = 5      # PRD §2.9: 'absolute minimum quorum of 5 voters'


# ---------------------------------------------------------------------------
# Lead-time constants (PRD §3.3)
# ---------------------------------------------------------------------------
LEAD_STANDARD_HOURS = 168    # PRD §3.3: '168 hours (which is 7 days) for STANDARD'
LEAD_EXPEDITED_HOURS = 24    # PRD §3.3: '24 hours (which is 1 day) for EXPEDITED'


# ---------------------------------------------------------------------------
# Rectification window (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
RECTIFICATION_WINDOW_DAYS = 30  # PRD §3.5: 'due_at ... 30 calendar days'


# ---------------------------------------------------------------------------
# Safety alert thresholds (PRD §3.7)
# ---------------------------------------------------------------------------
SAFETY_ALERT_THRESHOLD = 3   # PRD §3.7: 'at least 3 serious events'
SAFETY_ALERT_RATE = 0.20     # PRD §3.7: 'at or above 0.20 (twenty percent)'


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_quorum_required(eligible_voter_count: int) -> int:
    """PRD §2.9: 'multiply percent by the eligible count first, take the
    ceiling next, then take the maximum with the absolute floor of 5
    voters last.'"""
    return max(
        QUORUM_MIN_ABSOLUTE,
        math.ceil(QUORUM_PERCENT / 100.0 * eligible_voter_count),
    )


def ceil_two_thirds(votes_cast: int) -> int:
    """PRD §3.5 (initial-review tally): 'the sum of APPROVE and
    APPROVE_WITH_MODIFICATION votes is at least two-thirds of the votes
    cast (rounded up to the nearest whole vote — for example, with 7
    cast votes the threshold is 5 approving votes)'."""
    return math.ceil(2 * votes_cast / 3)


def ceil_half(votes_cast: int) -> int:
    """PRD §3.5: 'the count of DEFER votes is at least half of the votes
    cast (rounded up to the nearest whole vote)'."""
    return math.ceil(votes_cast / 2)


__all__ = [
    "QUORUM_PERCENT",
    "QUORUM_MIN_ABSOLUTE",
    "LEAD_STANDARD_HOURS",
    "LEAD_EXPEDITED_HOURS",
    "RECTIFICATION_WINDOW_DAYS",
    "SAFETY_ALERT_THRESHOLD",
    "SAFETY_ALERT_RATE",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "compute_quorum_required",
    "ceil_two_thirds",
    "ceil_half",
]
