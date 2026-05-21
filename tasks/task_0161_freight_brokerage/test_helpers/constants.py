"""Domain thresholds and pricing constants — PRD §3.4 / §3.7 / §3.8 / §3.9.

Numeric constants pinned by the PRD: spot-rate table, factoring tier
caps and rates, detention increment, claim penalties, safety thresholds.
"""
from __future__ import annotations

from typing import Dict


# ---------------------------------------------------------------------------
# Spot rate table — PRD §3.4
# ---------------------------------------------------------------------------
SPOT_BASE_CENTS_PER_EQUIPMENT: Dict[str, int] = {
    "DRY_VAN": 30_000,
    "REEFER": 50_000,
    "FLATBED": 40_000,
}

SPOT_PER_UNIT_CENTS: Dict[str, int] = {
    "DRY_VAN": 10,
    "REEFER": 18,
    "FLATBED": 14,
}


# ---------------------------------------------------------------------------
# Detention — PRD §3.7
# ---------------------------------------------------------------------------
DETENTION_INCREMENT_MINUTES: int = 15
DEFAULT_DETENTION_FREE_MINUTES: int = 120
DEFAULT_DETENTION_RATE_CENTS_PER_15MIN: int = 1500


# ---------------------------------------------------------------------------
# Factoring tiers — PRD §3.8
# ---------------------------------------------------------------------------
FACTORING_TIER_A_CAP_CENTS: int = 100_000
FACTORING_TIER_B_CAP_CENTS: int = 500_000
FACTORING_TIER_A_RATE: float = 0.030
FACTORING_TIER_B_RATE: float = 0.020
FACTORING_TIER_C_RATE: float = 0.010


# ---------------------------------------------------------------------------
# Claim penalties — PRD §3.9
# ---------------------------------------------------------------------------
CLAIM_TYPE_PENALTY: Dict[str, int] = {
    "DAMAGE": 100,
    "SHORTAGE": 60,
    "OVERCHARGE": 30,
    "LATE_DELIVERY": 40,
}

SMARTWAY_BREACH_PENALTY: int = 50


# ---------------------------------------------------------------------------
# Safety thresholds — PRD §3.3 / §3.9
# ---------------------------------------------------------------------------
SAFETY_SCORE_INITIAL: int = 1000
SAFETY_SUSPEND_THRESHOLD: int = 600    # < this triggers auto-SUSPENDED
SAFETY_REQUALIFY_THRESHOLD: int = 700  # >= this required for /requalify
SAFETY_SCORE_FLOOR: int = 0


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — convenience values for factories
# ---------------------------------------------------------------------------
TEST_DEFAULTS: Dict[str, object] = {
    "BROKERAGE_NAME": "Test Brokerage",
    "BROKERAGE_MC": "MC123456",
    "FACTORING_RESERVE_PCT": 5.00,
    "DETENTION_FREE_MINUTES": DEFAULT_DETENTION_FREE_MINUTES,
    "DETENTION_RATE_CENTS_PER_15MIN": DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    "SHIPPER_NAME": "Acme Shipper",
    "SHIPPER_CREDIT_LIMIT": 10_000_000,
    "CARRIER_NAME": "Test Carrier LLC",
    "EQUIPMENT_DRY_VAN": "DRY_VAN",
}


__all__ = [
    "SPOT_BASE_CENTS_PER_EQUIPMENT",
    "SPOT_PER_UNIT_CENTS",
    "DETENTION_INCREMENT_MINUTES",
    "DEFAULT_DETENTION_FREE_MINUTES",
    "DEFAULT_DETENTION_RATE_CENTS_PER_15MIN",
    "FACTORING_TIER_A_CAP_CENTS",
    "FACTORING_TIER_B_CAP_CENTS",
    "FACTORING_TIER_A_RATE",
    "FACTORING_TIER_B_RATE",
    "FACTORING_TIER_C_RATE",
    "CLAIM_TYPE_PENALTY",
    "SMARTWAY_BREACH_PENALTY",
    "SAFETY_SCORE_INITIAL",
    "SAFETY_SUSPEND_THRESHOLD",
    "SAFETY_REQUALIFY_THRESHOLD",
    "SAFETY_SCORE_FLOOR",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
