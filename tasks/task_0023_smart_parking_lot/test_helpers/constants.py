"""Domain constants extracted from the PRD.

Numeric thresholds, default values, fixed multipliers and bps constants
used across the test suite. Values quoted verbatim from PRD §3.
"""
from __future__ import annotations
from typing import Dict


# ---------------------------------------------------------------------------
# ParkingLot defaults (PRD §3.1)
# ---------------------------------------------------------------------------
DEFAULT_FREE_MINUTES = 15
DEFAULT_TOW_GRACE_MINUTES = 5
DEFAULT_RESERVATION_HOLD_MINUTES = 15
DEFAULT_NO_SHOW_PENALTY_CENTS = 500
DEFAULT_PARTNER_SHARE_BPS = 0


# ---------------------------------------------------------------------------
# Card binding cardinality (PRD §3.3)
# ---------------------------------------------------------------------------
STORED_VALUE_MAX_BINDINGS = 1
MONTHLY_MAX_BINDINGS = 4


# ---------------------------------------------------------------------------
# Fine amount table (PRD §3.6)
# ---------------------------------------------------------------------------
TYPE_BASE_CENTS: Dict[str, int] = {
    "OVERSTAY": 2000,
    "NON_PAYING": 3000,
    "BLOCKING": 5000,
    "WRONG_ZONE": 4000,
}

TYPE_MULTIPLIER: Dict[str, float] = {
    "OVERSTAY": 1.0,
    "NON_PAYING": 1.5,
    "BLOCKING": 2.0,
    "WRONG_ZONE": 1.25,
}

PHOTO_SURCHARGE_CENTS = 1500
REPEAT_TIER1_CENTS = 1000
REPEAT_TIER2_CENTS = 2500
REPEAT_TIER3_CENTS = 5000


# ---------------------------------------------------------------------------
# Reservation discount and revenue split (PRD §3.4, §3.7)
# ---------------------------------------------------------------------------
MATCH_DISCOUNT_BPS = 1000          # 10.00% discount
BPS_DENOMINATOR = 10000


# ---------------------------------------------------------------------------
# Time-based windows (PRD §3.4, §3.5, §3.6, §3.7)
# ---------------------------------------------------------------------------
RESERVATION_LATE_GRACE_MINUTES = 5     # scheduled_start_at - 5 minutes
NO_CANCEL_WINDOW_MINUTES = 30          # half-penalty applies inside this
DISPUTE_WINDOW_DAYS = 14
TOW_MINIMUM_HOURS = 24
REFUND_WINDOW_DAYS = 7
REPEAT_OFFENDER_WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Plate normalization (PRD §3.2)
# ---------------------------------------------------------------------------
PLATE_REGEX = r"^[A-Z0-9-]{1,12}$"
PLATE_MAX_LEN = 12


# ---------------------------------------------------------------------------
# Test clock baselines. The runner starts every test in an isolated
# DB / clock state, so each test that needs deterministic time math
# advances the clock to one of these instants up front.
# ---------------------------------------------------------------------------
CLOCK_BASELINE_ISO = "2026-01-01T00:00:00.000Z"
FAR_FUTURE_ISO = "2099-12-31T23:59:59.000Z"
