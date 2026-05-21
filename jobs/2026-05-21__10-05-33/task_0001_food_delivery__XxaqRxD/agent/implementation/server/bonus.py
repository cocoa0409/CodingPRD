"""Rider bonus-tier computation per PRD §3.3."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def round_half_up_to(value: float | Decimal, places: int) -> Decimal:
    q = Decimal(10) ** -places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    rating_norm = rating / 5.0
    score = (
        Decimal(str(on_time_rate)) * Decimal("0.6")
        + Decimal(str(acceptance_rate)) * Decimal("0.3")
        + Decimal(str(rating_norm)) * Decimal("0.1")
    )
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if score >= Decimal("0.900"):
        return "PLATINUM"
    if score >= Decimal("0.800"):
        return "GOLD"
    if score >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"


def recompute_rider_metrics(rider: dict) -> None:
    """Recompute on_time_rate, acceptance_rate, rating, and bonus_tier in place."""
    # acceptance_rate over last 30 offers (ACCEPTED or REJECTED outcomes only)
    offers = rider.get("_offer_outcomes", [])
    # Only ACCEPTED and REJECTED count per PRD; CANCELLED-after-accept does not.
    relevant_offers = [o for o in offers if o in ("ACCEPTED", "REJECTED")][-30:]
    if rider.get("_completed_count", 0) < 10:
        on_time_rate = 1.0
    else:
        on_time_window = rider.get("_on_time_history", [])[-30:]
        if not on_time_window:
            on_time_rate = 1.0
        else:
            on_time_rate = sum(1 for v in on_time_window if v) / len(on_time_window)

    if rider.get("_completed_count", 0) < 10:
        # The PRD ties the "fewer than 10 completed deliveries → 1.0" rule to on_time_rate explicitly.
        # For acceptance_rate, no such initial-floor rule exists; we still default to 1.0 when
        # the rider has had no offers at all so a brand new rider starts at 1.0 (matches PRD §3.3
        # "likewise initialized to 1.0").
        if not relevant_offers:
            acceptance_rate = 1.0
        else:
            acceptance_rate = sum(1 for o in relevant_offers if o == "ACCEPTED") / len(relevant_offers)
    else:
        if not relevant_offers:
            acceptance_rate = 1.0
        else:
            acceptance_rate = sum(1 for o in relevant_offers if o == "ACCEPTED") / len(relevant_offers)

    ratings = rider.get("_rating_history", [])[-30:]
    if rider.get("_completed_count", 0) < 10 or not ratings:
        rating = 5.0
    else:
        rating = sum(ratings) / len(ratings)

    rider["on_time_rate"] = max(0.0, min(1.0, on_time_rate))
    rider["acceptance_rate"] = max(0.0, min(1.0, acceptance_rate))
    rider["rating"] = max(0.0, min(5.0, rating))
    rider["bonus_tier"] = compute_bonus_tier(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])
