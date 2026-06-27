"""Inventory allocation: First-Expiry-First-Out (PRD §2.9)."""
import db
from clock import parse_iso


def candidate_lots(store_id, product_id):
    """AVAILABLE lots for (store, product) with free units > 0, FEFO-ordered.

    Order: expiry_date ASC, then received_at ASC, then created_at ASC. Never id.
    Free units = quantity_on_hand - quantity_reserved.
    """
    lots = [
        lot for lot in db.inventory_lots.values()
        if lot["store_id"] == store_id
        and lot["product_id"] == product_id
        and lot["status"] == "AVAILABLE"
        and (lot["quantity_on_hand"] - lot["quantity_reserved"]) > 0
    ]
    lots.sort(key=lambda lot: (
        parse_iso(lot["expiry_date"]),
        parse_iso(lot["received_at"]),
        lot["created_at"],
    ))
    return lots


def free_unit_sum(store_id, product_id):
    return sum(
        lot["quantity_on_hand"] - lot["quantity_reserved"]
        for lot in candidate_lots(store_id, product_id)
    )


def plan_allocation(store_id, product_id, units):
    """Return a list of (lot, take) covering `units`, or None if insufficient.

    All-or-nothing: returns None when free units < requested (PRD §2.9). The last
    lot may be drawn partially.
    """
    lots = candidate_lots(store_id, product_id)
    remaining = units
    plan = []
    for lot in lots:
        if remaining <= 0:
            break
        free = lot["quantity_on_hand"] - lot["quantity_reserved"]
        take = min(free, remaining)
        if take > 0:
            plan.append((lot, take))
            remaining -= take
    if remaining > 0:
        return None
    return plan
