"""Loyalty accrual: lifetime spend, points, and tier recompute (PRD §2.8)."""
from services.derive import compute_loyalty_tier, LOYALTY_POINTS_PER_DOLLAR


def whole_dollar_points(net_cents, multiplier=1):
    """Points = floor(net_cents / 100) * POINTS_PER_DOLLAR * multiplier."""
    return (net_cents // 100) * LOYALTY_POINTS_PER_DOLLAR * multiplier


def accrue(customer, net_cents, earned_points):
    """Add net spend + points to a customer and recompute loyalty_tier.

    Note: loyalty_tier is a derived field computed at serialization time, but the
    PRD describes it as 'recomputed' on accrual; the derivation is a pure function
    of lifetime_spend_cents so storing it stays consistent. We do not store it as
    a field of record (serialize computes it), but we keep this helper to mutate
    spend/points cohesively.
    """
    customer["lifetime_spend_cents"] += net_cents
    customer["loyalty_points"] += earned_points
    # loyalty_tier is derived from lifetime_spend_cents at read time.
    _ = compute_loyalty_tier(customer["lifetime_spend_cents"])
