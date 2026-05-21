"""Calculation rules — offer total comp, referral bonus, panel average, diversity progress.

All money is integer cents; precision is enforced with Decimal + ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


# ---------- offer_total_comp ----------

def _round_half_up_dollars_from_cents(cents: int) -> int:
    """Convert cents to whole dollars with round-half-up."""
    quantized = (Decimal(cents) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def offer_total_comp_cents(base_cents: int, signon_cents: int, equity_cents: int) -> int:
    """Round each component to whole dollars FIRST, sum, then express in cents (×100)."""
    base_d = _round_half_up_dollars_from_cents(base_cents)
    signon_d = _round_half_up_dollars_from_cents(signon_cents)
    equity_d = _round_half_up_dollars_from_cents(equity_cents)
    return (base_d + signon_d + equity_d) * 100


# ---------- referral_bonus_amount ----------

SENIORITY_TIERS_CENTS = {
    "JUNIOR": 150000,
    "MID": 250000,
    "SENIOR": 500000,
    "STAFF": 750000,
    "PRINCIPAL": 1000000,
}
UPLIFT_RATE = Decimal("0.50")
UPLIFT_CAP_DEFAULT_CENTS = 200000
UPLIFT_CAP_GOAL_CENTS = 400000
WAITING_DAYS = 90


def referral_bonus_amounts(
    seniority_level: str, is_protected: bool, has_diversity_goal: bool
) -> tuple[int, int]:
    base = SENIORITY_TIERS_CENTS[seniority_level]
    if is_protected:
        raw = (Decimal(base) * UPLIFT_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        uplift = int(raw)
        cap = UPLIFT_CAP_GOAL_CENTS if has_diversity_goal else UPLIFT_CAP_DEFAULT_CENTS
        uplift = min(uplift, cap)
    else:
        uplift = 0
    return base, uplift


# ---------- panel_average_score ----------

def panel_average(scores: Iterable[int]) -> float | None:
    """Mean of overall_score values rounded half-up to 2 decimals; None on empty set."""
    score_list = list(scores)
    if not score_list:
        return None
    total = Decimal(sum(score_list))
    n = Decimal(len(score_list))
    avg = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Return as a native float; JSON encoding keeps two decimals through string display via Python's default repr.
    return float(avg)


# ---------- diversity_goal_progress ----------

def percentage_round_2(protected_count: int, total: int) -> float:
    if total == 0:
        return 0.00
    pct = (Decimal(100) * Decimal(protected_count) / Decimal(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(pct)
