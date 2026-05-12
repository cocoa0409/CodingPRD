"""Domain constants extracted verbatim from the PRD.

Numeric thresholds, default values, fixed multipliers, and bps constants
used across the test suite. Values quoted from PRD §2 and §3.
"""
from __future__ import annotations
from typing import Dict


# ---------------------------------------------------------------------------
# Basis-point arithmetic (PRD §2.8)
# ---------------------------------------------------------------------------
BPS_DENOMINATOR = 10000
PARITY_TOLERANCE_BP = 100  # PRD §3.3: tolerance is one percent / 100 basis points

# ---------------------------------------------------------------------------
# RoomType constraints (PRD §3.1)
# ---------------------------------------------------------------------------
ROOM_TYPE_CODE_MIN_LEN = 2
ROOM_TYPE_CODE_MAX_LEN = 8
ROOM_TYPE_BASE_RATE_MIN = 1000          # >= $10
ROOM_TYPE_MAX_OCCUPANCY_MIN = 1
ROOM_TYPE_MAX_OCCUPANCY_MAX = 10

# ---------------------------------------------------------------------------
# Channel constraints (PRD §3.2)
# ---------------------------------------------------------------------------
CHANNEL_COMMISSION_MIN_BP = 0
CHANNEL_COMMISSION_MAX_BP = 5000        # max 50% commission
CHANNEL_PRIORITY_MIN = 1

# ---------------------------------------------------------------------------
# ChannelRatePlanMapping constraints (PRD §3.2)
# ---------------------------------------------------------------------------
INVENTORY_SHARE_MIN_BP = 0
INVENTORY_SHARE_MAX_BP = 10000
INVENTORY_SHARE_TOTAL_CAP_BP = 10000    # PRD §3.2: 10000-basis-point ceiling

# ---------------------------------------------------------------------------
# OverbookingPolicy constraints (PRD §3.4)
# ---------------------------------------------------------------------------
OVERBOOK_RATIO_MIN_BP = 0
OVERBOOK_RATIO_MAX_BP = 5000            # +50% over physical capacity
NO_SHOW_PROBABILITY_MIN_BP = 0
NO_SHOW_PROBABILITY_MAX_BP = 10000
WALKOUT_COMPENSATION_MIN = 0

# ---------------------------------------------------------------------------
# Refund tier table (PRD §3.5)
# Maps refund_tier_code -> ordered list of (lead_time_threshold_hours, ratio_bp)
# Read as: bucket where lead_time_hours >= threshold yields ratio_bp.
# Lookup walks list; first matching bucket wins.
# ---------------------------------------------------------------------------
REFUND_TIER_TABLE: Dict[str, list] = {
    "FLEXIBLE": [(24, 10000), (0, 5000)],
    "MODERATE": [(168, 10000), (72, 5000), (0, 0)],
    "STRICT": [(336, 5000), (0, 0)],
    "NON_REFUNDABLE": [(0, 0)],
}

# ---------------------------------------------------------------------------
# No-show charge ratios (PRD §3.7)
# Tier -> ratio_bp applied to booked_total_cents (NON_REFUNDABLE & STRICT
# = full charge implemented as 10000 bp for uniform rounding semantics).
# ---------------------------------------------------------------------------
NO_SHOW_CHARGE_RATIO_BP: Dict[str, int] = {
    "FLEXIBLE": 1000,             # 10%
    "MODERATE": 5000,             # 50%
    "STRICT": 10000,              # 100%
    "NON_REFUNDABLE": 10000,      # 100%
}

# ---------------------------------------------------------------------------
# Modification cutoff (PRD §3.5)
# ---------------------------------------------------------------------------
MODIFICATION_CUTOFF_HOURS = 24
NO_SHOW_GRACE_HOURS = 24          # PRD §3.7: 24h after check_in_date

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Test clock baselines. The runner starts every test in an isolated
# DB / clock state, so each test that needs deterministic time math
# advances the clock to a known instant up front.
# ---------------------------------------------------------------------------
CLOCK_BASELINE_ISO = "2026-01-01T00:00:00.000Z"
FAR_FUTURE_ISO = "2099-12-31T23:59:59.000Z"


__all__ = [
    "BPS_DENOMINATOR",
    "PARITY_TOLERANCE_BP",
    "ROOM_TYPE_CODE_MIN_LEN",
    "ROOM_TYPE_CODE_MAX_LEN",
    "ROOM_TYPE_BASE_RATE_MIN",
    "ROOM_TYPE_MAX_OCCUPANCY_MIN",
    "ROOM_TYPE_MAX_OCCUPANCY_MAX",
    "CHANNEL_COMMISSION_MIN_BP",
    "CHANNEL_COMMISSION_MAX_BP",
    "CHANNEL_PRIORITY_MIN",
    "INVENTORY_SHARE_MIN_BP",
    "INVENTORY_SHARE_MAX_BP",
    "INVENTORY_SHARE_TOTAL_CAP_BP",
    "OVERBOOK_RATIO_MIN_BP",
    "OVERBOOK_RATIO_MAX_BP",
    "NO_SHOW_PROBABILITY_MIN_BP",
    "NO_SHOW_PROBABILITY_MAX_BP",
    "WALKOUT_COMPENSATION_MIN",
    "REFUND_TIER_TABLE",
    "NO_SHOW_CHARGE_RATIO_BP",
    "MODIFICATION_CUTOFF_HOURS",
    "NO_SHOW_GRACE_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "CLOCK_BASELINE_ISO",
    "FAR_FUTURE_ISO",
]
