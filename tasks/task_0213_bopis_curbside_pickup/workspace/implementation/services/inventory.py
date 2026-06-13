"""Inventory availability model + movement ledger (PRD §2.6)."""

from db import db, stamp_ledger


def recompute_available(inv):
    """available = max(0, on_hand - reserved). Integer units, no rounding."""
    inv["available"] = max(0, inv["on_hand"] - inv["reserved"])


def find_inventory(store_id, product_id):
    for inv in db.store_inventory.values():
        if inv["store_id"] == store_id and inv["product_id"] == product_id:
            return inv
    return None


def append_movement(inv, movement_type, delta_on_hand, delta_reserved, reason):
    rec = {
        "store_inventory_id": inv["id"],
        "movement_type": movement_type,
        "delta_on_hand": delta_on_hand,
        "delta_reserved": delta_reserved,
        "reason": reason,
    }
    stamp_ledger(rec)
    db.inventory_movements[rec["id"]] = rec
    return rec


def reserve(inv, qty, reason):
    inv["reserved"] += qty
    recompute_available(inv)
    append_movement(inv, "RESERVE", 0, qty, reason)


def release(inv, qty, reason):
    inv["reserved"] -= qty
    recompute_available(inv)
    append_movement(inv, "RELEASE", 0, -qty, reason)


def pick_remove_full(inv, qty, reason):
    """Full pick: on_hand and reserved both fall by qty (line qty_reserved -> 0)."""
    inv["on_hand"] -= qty
    inv["reserved"] -= qty
    recompute_available(inv)
    append_movement(inv, "PICK_REMOVE", -qty, -qty, reason)


def pick_remove_short(inv, qty_picked, qty_unpicked, reason):
    """Short pick: PICK_REMOVE pulls qty_picked off the shelf (those units stay
    reserved for the customer), then RELEASE frees the unpicked reservation."""
    inv["on_hand"] -= qty_picked
    append_movement(inv, "PICK_REMOVE", -qty_picked, 0, reason)
    inv["reserved"] -= qty_unpicked
    append_movement(inv, "RELEASE", 0, -qty_unpicked, reason)
    recompute_available(inv)


def restock(inv, qty, reason):
    inv["on_hand"] += qty
    recompute_available(inv)
    append_movement(inv, "RESTOCK", qty, 0, reason)
