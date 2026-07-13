"""Loyalty: the conserved points ledger and the two tier-evaluation variants."""
from db import base_record, db, touch
from services.pricing import (
    TIER_RANK,
    TIER_THRESHOLD_ROUGE_CENTS,
    TIER_THRESHOLD_VIB_CENTS,
)
from util import iso


def append_ledger(customer, entry_type, delta_points, order_id=None):
    """The only way a balance ever moves: append an entry, then mirror it.
    points_balance always equals the sum of delta_points (PRD 2.7)."""
    customer["points_balance"] += delta_points
    entry = base_record(versioned=False)
    entry.update({
        "customer_id": customer["id"],
        "order_id": order_id,
        "entry_type": entry_type,
        "delta_points": delta_points,
        "balance_after": customer["points_balance"],
    })
    db.ledger[entry["id"]] = entry
    return entry


def target_tier(qualifying_spend_cents):
    if qualifying_spend_cents >= TIER_THRESHOLD_ROUGE_CENTS:
        return "ROUGE"
    if qualifying_spend_cents >= TIER_THRESHOLD_VIB_CENTS:
        return "VIB"
    return "INSIDER"


def tier_evaluation_rolling(customer):
    """Monotone: writes the target tier only when it ranks strictly higher."""
    target = target_tier(customer["qualifying_spend_cents"])
    if TIER_RANK[target] > TIER_RANK[customer["tier"]]:
        customer["tier"] = target
        return True
    return False


def tier_evaluation_checkpoint(customer):
    """Non-monotone: re-derives unconditionally (so it downgrades), then resets
    the cycle."""
    customer["tier"] = target_tier(customer["qualifying_spend_cents"])
    customer["qualifying_spend_cents"] = 0
    customer["cycle_started_at"] = iso(db.clock)
    touch(customer)
    return customer
