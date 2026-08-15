"""fefo_allocation (PRD §3.6): first-expiry-first-out backflush planning for
GIFT_ASSEMBLY completion.

Eligible pool per component: lots of that component product with
status == ACTIVE, quality_status == OK, expiry_date strictly later than the
current logical clock, and qty_on_hand > 0. Ordered by expiry_date ascending,
ties broken by created_at ascending. If the pool cannot cover
qty_per_set * output_units for every component, the whole completion is
rejected with no partial deduction (atomicity: plan first, then apply).
"""
from db import now, store


def plan_fefo(gift_product_id, output_units):
    """Return a list of (lot, take) deductions, or None when the eligible pool
    cannot cover some component's need."""
    plan = []
    for gc in store.gift_components.values():
        if gc["gift_product_id"] != gift_product_id:
            continue
        needed = gc["qty_per_set"] * output_units
        if needed <= 0:
            continue
        pool = [
            lot for lot in store.lots.values()
            if lot["product_id"] == gc["component_product_id"]
            and lot["status"] == "ACTIVE"
            and lot["quality_status"] == "OK"
            and lot["expiry_date"] > now()
            and lot["qty_on_hand"] > 0
        ]
        # Stable sort: dict insertion order breaks remaining ties.
        pool.sort(key=lambda lot: (lot["expiry_date"], lot["created_at"]))
        remaining = needed
        for lot in pool:
            take = min(remaining, lot["qty_on_hand"])
            if take > 0:
                plan.append((lot, take))
                remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            return None
    return plan
