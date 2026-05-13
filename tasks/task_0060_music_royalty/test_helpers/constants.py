"""Domain thresholds and numeric constants from the PRD.

Tax-rate table (PRD §2.6): country code → withholding rate. Admin-fee
tier breakpoints (PRD §3.8). Classification thresholds (PRD §3.9).
Pagination defaults (PRD §2.3).
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Admin-fee tiers (PRD §3.8)
# Tier 1: gross < 10_000_000 cents → 5%
# Tier 2: 10_000_000 cents ≤ gross < 100_000_000 cents → 4% on portion above tier-1 cap
# Tier 3: gross ≥ 100_000_000 cents → 3% on portion above tier-2 cap
# ---------------------------------------------------------------------------
TIER1_CAP_CENTS = 10_000_000
TIER2_CAP_CENTS = 100_000_000
TIER1_RATE = Decimal("0.05")
TIER2_RATE = Decimal("0.04")
TIER3_RATE = Decimal("0.03")


# ---------------------------------------------------------------------------
# Tax rates per ISO 3166-1 alpha-2 (PRD §2.6)
# ---------------------------------------------------------------------------
TAX_RATE_BY_JURISDICTION: Dict[str, Decimal] = {
    "US": Decimal("0.30"),
    "GB": Decimal("0.20"),
    "DE": Decimal("0.26"),
    "JP": Decimal("0.20"),
    "CN": Decimal("0.10"),
    "FR": Decimal("0.25"),
    "IE": Decimal("0.20"),
}
TAX_RATE_DEFAULT = Decimal("0.30")


# ---------------------------------------------------------------------------
# Playback classification thresholds (PRD §3.9)
# - FULL_PLAY when play_duration_seconds ≥ 95% of Work.duration_seconds
# - SKIP when play_duration_seconds < 30% of Work.duration_seconds
# ---------------------------------------------------------------------------
FULL_PLAY_THRESHOLD_RATIO = Decimal("0.95")
SKIP_THRESHOLD_RATIO = Decimal("0.30")


# ---------------------------------------------------------------------------
# Dispute exposure scoring (PRD §3.11)
# ---------------------------------------------------------------------------
FORWARD_OPEN_DISPUTE_WEIGHT = Decimal("0.6")
FORWARD_RATIO_WEIGHT = Decimal("0.4")
CHRONOLOGICAL_DECAY_FACTOR = Decimal("0.9")


# ---------------------------------------------------------------------------
# Payment retry cap (PRD §3.13)
# ---------------------------------------------------------------------------
PAYMENT_RETRY_CAP = 3


# ---------------------------------------------------------------------------
# Playback temporal limits (PRD §2.10 priority 21)
# ---------------------------------------------------------------------------
PLAYBACK_WINDOW_MAX_DAYS = 31


# ---------------------------------------------------------------------------
# Co-creator constraints (PRD §3.1)
# ---------------------------------------------------------------------------
CO_CREATORS_MIN = 1
CO_CREATORS_MAX = 16


def round_half_up(value: Decimal) -> int:
    """Round to whole cents using round half up (PRD §2.6)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


__all__ = [
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "TIER1_CAP_CENTS", "TIER2_CAP_CENTS",
    "TIER1_RATE", "TIER2_RATE", "TIER3_RATE",
    "TAX_RATE_BY_JURISDICTION", "TAX_RATE_DEFAULT",
    "FULL_PLAY_THRESHOLD_RATIO", "SKIP_THRESHOLD_RATIO",
    "FORWARD_OPEN_DISPUTE_WEIGHT", "FORWARD_RATIO_WEIGHT",
    "CHRONOLOGICAL_DECAY_FACTOR",
    "PAYMENT_RETRY_CAP", "PLAYBACK_WINDOW_MAX_DAYS",
    "CO_CREATORS_MIN", "CO_CREATORS_MAX",
    "round_half_up",
]
