"""All four calculations from SCAFFOLD §1.3 — booking_quote, sitter_payout,
sitter_tier_score, claim_payout. Integer cents, round-half-up at pinned points.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


# ---------- Constants ----------
BASE_RATE_BY_SERVICE = {
    "WALK_30MIN": 2000,
    "WALK_60MIN": 3500,
    "BOARDING_OVERNIGHT": 8000,
    "DAYCARE": 5000,
}
TIER_MULT = {
    "BRONZE": Decimal("1.00"),
    "SILVER": Decimal("1.15"),
    "GOLD": Decimal("1.30"),
}
TIME_FACTOR = {
    "STANDARD": Decimal("1.00"),
    "PEAK": Decimal("1.20"),
    "OVERNIGHT": Decimal("1.30"),
}
RECUR_DISCOUNT = {
    "NONE": Decimal("0.00"),
    "WEEKLY": Decimal("0.10"),
    "BIWEEKLY": Decimal("0.05"),
}

PLATFORM_FEE_PCT = Decimal("0.15")

# sitter_tier_score constants
W_RATING = Decimal("0.5")
W_BOOKINGS = Decimal("0.3")
BASE = 10
CLAIM_PENALTY = 15
CLAIM_CAP = 45
BOOKINGS_CAP = 40
SILVER_MIN = 40
GOLD_MIN = 70

# claim_payout constants
TIER_DEDUCTIBLE = {
    "BRONZE": 10000,
    "SILVER": 5000,
    "GOLD": 2500,
}
MAX_PAYOUT_CENTS = 500000


def _round_half_up(x: Decimal) -> int:
    """Round a Decimal half-up to the nearest integer."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- booking_quote ----------
def compute_booking_quote(
    *,
    service_type: str,
    sitter_tier: str,
    time_of_day: str,
    recurring_cadence: str,
    emergency_surcharge_cents: int,
) -> int:
    """Three pinned rounds at step1, step2, discount_cents."""
    base_rate = Decimal(BASE_RATE_BY_SERVICE[service_type])
    tier_mult = TIER_MULT[sitter_tier]
    time_factor = TIME_FACTOR[time_of_day]
    recur_discount = RECUR_DISCOUNT[recurring_cadence]

    step1 = _round_half_up(base_rate * tier_mult)
    step2 = _round_half_up(Decimal(step1) * time_factor)
    discount_cents = _round_half_up(Decimal(step2) * recur_discount)

    quote = step2 - discount_cents + int(emergency_surcharge_cents)
    return quote


# ---------- sitter_payout ----------
def compute_sitter_payout_provisional(booking_quote_cents: int) -> int:
    """Provisional variant: quote - platform_fee."""
    platform_fee = _round_half_up(Decimal(booking_quote_cents) * PLATFORM_FEE_PCT)
    return booking_quote_cents - platform_fee


def compute_sitter_payout_final(
    booking_quote_cents: int, tip_cents: int, incident_deduction_cents: int
) -> int:
    """Final variant: max(0, quote - fee + tip - incident)."""
    platform_fee = _round_half_up(Decimal(booking_quote_cents) * PLATFORM_FEE_PCT)
    return max(0, (booking_quote_cents - platform_fee) + tip_cents - incident_deduction_cents)


# ---------- sitter_tier_score ----------
def compute_sitter_tier(
    *,
    total_completed_bookings: int,
    total_rating_sum: int,
    total_rating_count: int,
    claim_count: int,
) -> tuple[int, str]:
    """Two pinned rounds at rating_score and weighted_sum.

    Returns (tier_score, tier).
    """
    # rating_score: pinned round 1
    if total_rating_count > 0:
        avg_rating = Decimal(total_rating_sum) / Decimal(total_rating_count)
        rating_score = _round_half_up(avg_rating * Decimal(20))
    else:
        rating_score = 60

    bookings_score = min(total_completed_bookings, BOOKINGS_CAP)
    claim_penalty = min(claim_count * CLAIM_PENALTY, CLAIM_CAP)

    # weighted_sum: pinned round 2
    weighted = Decimal(rating_score) * W_RATING + Decimal(bookings_score) * W_BOOKINGS + Decimal(BASE)
    raw = _round_half_up(weighted)

    tier_score = max(0, raw - claim_penalty)

    if tier_score >= GOLD_MIN:
        tier = "GOLD"
    elif tier_score >= SILVER_MIN:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    return tier_score, tier


# ---------- claim_payout ----------
def compute_claim_payout(*, amount_cents: int, sitter_tier_snapshot: str) -> int:
    """All integer math; payout = max(0, min(amount, MAX_PAYOUT) - deductible)."""
    deductible = TIER_DEDUCTIBLE[sitter_tier_snapshot]
    capped = min(int(amount_cents), MAX_PAYOUT_CENTS)
    return max(0, capped - deductible)


# Tier-ordering helper (for "did tier drop?" check on cascade #2)
_TIER_RANK = {"BRONZE": 0, "SILVER": 1, "GOLD": 2}


def tier_dropped(old_tier: str, new_tier: str) -> bool:
    return _TIER_RANK[new_tier] < _TIER_RANK[old_tier]
