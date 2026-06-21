"""Inventory rollups, FIFO ordering, reservation and consumption.

Rollups (PRD §2.9):
  total_on_hand_qty = sum remaining_qty over lots in {AVAILABLE, QUARANTINED}
  available_qty     = sum remaining_qty over AVAILABLE lots
                      minus qty currently RESERVED by open kit requirements
"""

import db


def lots_for_part(part_id):
    return [l for l in db.inventory_lots.values() if l["part_id"] == part_id]


def fifo_available_lots(part_id):
    """AVAILABLE lots for a part, ordered FIFO: received_at ASC, created_at ASC.

    Tie-break by the internal monotonic _seq (consistent with created_at).
    """
    avail = [l for l in lots_for_part(part_id) if l["status"] == "AVAILABLE"]
    return sorted(avail, key=lambda l: (l["received_at"], l.get("_seq", 0)))


def reserved_qty_for_part(part_id, exclude_kr_id=None):
    """Sum of reserved_qty across kit requirements (RESERVED status) for the part.

    Open reservations only (status RESERVED); RELEASED/CONSUMED do not hold stock.
    """
    total = 0
    for kr in db.kit_requirements.values():
        if kr["part_id"] != part_id:
            continue
        if exclude_kr_id is not None and kr["id"] == exclude_kr_id:
            continue
        if kr["status"] == "RESERVED":
            total += kr["reserved_qty"]
    return total


def recompute_part_rollups(part_id):
    part = db.parts.get(part_id)
    if part is None:
        return
    on_hand = 0
    available_phys = 0
    for l in lots_for_part(part_id):
        if l["status"] in ("AVAILABLE", "QUARANTINED"):
            on_hand += l["remaining_qty"]
        if l["status"] == "AVAILABLE":
            available_phys += l["remaining_qty"]
    reserved = reserved_qty_for_part(part_id)
    available = available_phys - reserved
    part["total_on_hand_qty"] = on_hand
    part["available_qty"] = available


def physical_available_qty(part_id):
    """Sum of remaining_qty over AVAILABLE lots (before subtracting reservations)."""
    return sum(l["remaining_qty"] for l in fifo_available_lots(part_id))


def free_available_qty(part_id):
    """Physical available minus currently reserved (the effective free pool)."""
    return physical_available_qty(part_id) - reserved_qty_for_part(part_id)
