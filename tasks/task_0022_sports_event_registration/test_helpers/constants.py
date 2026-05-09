"""Domain constants extracted from the PRD.

Numeric thresholds, percentages, and pinned values that the tests must
quote literally. Sourced from PRD §3.1 (capacity, registration window),
§3.6 (prize tiers, payout delay, currency factors), §3.8 (appeal window),
§2.13 (concurrency boundaries).
"""
from __future__ import annotations
from typing import Dict


# ---------------------------------------------------------------------------
# Capacity / draw (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
MAX_PARTICIPANTS = 256          # PRD §3.1: capacity_max no greater than 256
MIN_CAPACITY_MIN = 2            # PRD §3.1: capacity_min at least 2


# ---------------------------------------------------------------------------
# Prize tier percentages (PRD §3.6)
# ---------------------------------------------------------------------------
TIER_1_PCT = 50          # rank 1
TIER_2_PCT = 25          # rank 2
TIER_3_4_PCT = 10        # ranks 3 and 4 each
TIER_5_8_PCT_X100 = 125  # 1.25%; expressed as 125/10000

# Payout delay (PRD §3.6): scheduled_pay_at = starts_at + 7 * 24 * 3600 s
PAYOUT_DELAY_SECONDS = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Multi-currency factors (PRD §2.6, §3.6)
# ---------------------------------------------------------------------------
FRACTIONAL_UNITS: Dict[str, int] = {
    "USD": 100,
    "EUR": 100,
    "GBP": 100,
    "JPY": 1,
}


# ---------------------------------------------------------------------------
# Tax bounds (PRD §2.6)
# ---------------------------------------------------------------------------
TAX_PCT_MIN = 0.0
TAX_PCT_MAX = 50.0


# ---------------------------------------------------------------------------
# Ranking points (PRD §3.5)
# ---------------------------------------------------------------------------
WIN_POINTS_TEAM = 3
DRAW_POINTS_TEAM = 1


# ---------------------------------------------------------------------------
# Appeal / sanction window (PRD §3.8)
# ---------------------------------------------------------------------------
APPEAL_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# Participant scheduling buffer (PRD §3.2)
# ---------------------------------------------------------------------------
PARTICIPANT_ADJACENCY_BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Logical-clock baselines for deterministic time math.
# Tests build all timestamps relative to these instants so registration,
# event-start, and appeal-window arithmetic remains predictable across runs.
# ---------------------------------------------------------------------------
CLOCK_BASELINE_ISO = "2030-01-01T00:00:00.000Z"
FAR_FUTURE_ISO = "2099-12-31T23:59:59.000Z"
