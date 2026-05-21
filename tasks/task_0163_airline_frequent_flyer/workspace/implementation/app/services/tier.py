"""Tier evaluation helpers (calculations.tier_evaluation)."""

from __future__ import annotations

from datetime import datetime

TIER_ORDER = ["BASIC", "SILVER", "GOLD", "PLATINUM"]
TIER_RANK = {"BASIC": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}

# Tier bonus multipliers used at segment-accrual time.
TIER_BONUS = {
    "BASIC": 1.0,
    "SILVER": 1.25,
    "GOLD": 1.5,
    "PLATINUM": 2.0,
}

FARE_CLASS_MULT = {
    "ECONOMY": 5,
    "BUSINESS": 10,
    "FIRST": 12,
}


def awarded_tier(segments_final: int, points_final: int) -> str:
    if points_final >= 100000 or segments_final >= 100:
        return "PLATINUM"
    if points_final >= 50000 or segments_final >= 50:
        return "GOLD"
    if points_final >= 25000 or segments_final >= 25:
        return "SILVER"
    return "BASIC"


def projected_tier_eoy(qs: int, qp: int, now: datetime) -> str:
    days_elapsed = now.timetuple().tm_yday
    if days_elapsed <= 0:
        days_elapsed = 1
    projected_pts = (qp * 365) // days_elapsed
    projected_seg = (qs * 365) // days_elapsed
    return awarded_tier(projected_seg, projected_pts)


def rank(tier: str) -> int:
    return TIER_RANK.get(tier, 0)


def at_least(tier: str, minimum: str) -> bool:
    return rank(tier) >= rank(minimum)
