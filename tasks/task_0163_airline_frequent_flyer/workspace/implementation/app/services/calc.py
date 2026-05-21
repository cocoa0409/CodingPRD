"""Pure calculation rules (SCAFFOLD §1.3)."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

from . import tier as tier_svc


# -----------------------------------------------------------------------------
# segment_accrual — combinatorial / capped
# -----------------------------------------------------------------------------

MIN_PER_SEGMENT = 100
MAX_PER_SEGMENT = 50_000


def segment_accrual(base_fare_cents: int, flown_cabin: str, member_tier: str) -> int:
    base_dollars = base_fare_cents // 100  # floor
    fare_class_mult = tier_svc.FARE_CLASS_MULT[flown_cabin]
    tier_bonus = tier_svc.TIER_BONUS[member_tier]
    raw = base_dollars * fare_class_mult * tier_bonus
    floored = int(math.floor(raw))
    return max(MIN_PER_SEGMENT, min(MAX_PER_SEGMENT, floored))


# -----------------------------------------------------------------------------
# award_price — dual variant
# -----------------------------------------------------------------------------

CABIN_MULT = {"ECONOMY": 1.0, "BUSINESS": 2.0, "FIRST": 3.5}

FIXED_AWARD_TABLE: Dict[str, Dict[str, int]] = {
    "DOMESTIC":      {"ECONOMY": 12500, "BUSINESS": 25000, "FIRST": 40000},
    "INTERNATIONAL": {"ECONOMY": 30000, "BUSINESS": 70000, "FIRST": 110000},
}


def _demand_multiplier(load_factor: float) -> float:
    if load_factor < 0.50:
        return 0.8
    if load_factor < 0.80:
        return 1.0
    if load_factor < 0.95:
        return 1.5
    return 2.0


def award_price_dynamic(distance_miles: int, load_factor: float, cabin: str) -> int:
    demand = _demand_multiplier(load_factor)
    cabin_mult = CABIN_MULT[cabin]
    raw = distance_miles * 5 * demand * cabin_mult
    return int(math.floor(raw))


def award_price_fixed(route_region: str, cabin: str) -> int:
    return FIXED_AWARD_TABLE[route_region][cabin]


# -----------------------------------------------------------------------------
# upgrade_priority_score
# -----------------------------------------------------------------------------

def priority_score(member_tier: str, points_offered: int, waitlist_join_seq: int) -> int:
    tier_rank = tier_svc.TIER_RANK[member_tier]
    return tier_rank * 10_000_000 + points_offered - waitlist_join_seq


# -----------------------------------------------------------------------------
# gift_transfer — round-then-subtract
# -----------------------------------------------------------------------------

GIFT_FEE_RATE = Decimal("0.10")
GIFT_MIN = 1000
GIFT_MAX_PER_DAY_PER_SENDER = 50000


def gift_fee_and_delivered(amount: int) -> tuple[int, int]:
    raw_fee = Decimal(amount) * GIFT_FEE_RATE
    fee_points = int(raw_fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    delivered = amount - fee_points
    return fee_points, delivered
