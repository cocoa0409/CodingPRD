"""Inventory two-pool model + allocation cascades (PRD §2.5, §3.8, §3.9)."""
from db import db
from common import touch
from errors import err, ERR_INSUFFICIENT_INVENTORY, ERR_WAVE_CAPACITY_FULL


def group_and_count(product_ids):
    """Collapse a box's ordered product_ids to per-product requested qty (PRD §3.8)."""
    counts = {}
    order = []
    for pid in product_ids:
        if pid not in counts:
            counts[pid] = 0
            order.append(pid)
        counts[pid] += 1
    return [{"product_id": pid, "qty": counts[pid]} for pid in order]


def available(product):
    """available = on_hand_qty - allocated_qty (PRD §2.5)."""
    return product["on_hand_qty"] - product["allocated_qty"]


def reserve(box, wave):
    """allocation_fill calc (PRD §3.8). All-or-nothing fill check; returns line_items.

    Mutates products (allocated_qty) and wave (reserved_count, version) on success.
    Caller is responsible for the box/subscription wiring and the OCC pre-check.
    """
    line_items = group_and_count(box["product_ids"])

    # Per-product availability check first (PRD validation priority: safety before capacity).
    for li in line_items:
        product = db.products[li["product_id"]]
        if available(product) < li["qty"]:
            raise err(ERR_INSUFFICIENT_INVENTORY,
                      "A box product has insufficient available inventory.")

    # Capacity check (PRD priority 11, fiscal — evaluated after inventory safety).
    if wave["reserved_count"] >= wave["capacity"]:
        raise err(ERR_WAVE_CAPACITY_FULL, "Wave capacity is exhausted.")

    # Commit reservation: move units free -> reserved, bump wave reserved_count.
    for li in line_items:
        product = db.products[li["product_id"]]
        product["allocated_qty"] += li["qty"]
        touch(product)
    wave["reserved_count"] += 1
    touch(wave)
    return line_items


def release_allocation(alloc, revert_decision="CURATED"):
    """RESERVED -> RELEASED cascade (PRD §3.8).

    Returns reserved units to the free pool (decrement allocated_qty, on_hand
    untouched), decrements the holding wave's reserved_count, and reverts the
    linked box selection. `revert_decision` is the decision the box returns to:
    the manual/wave-cancel/charge-fail paths revert to CURATED per §3.8/§3.9,
    while the subscription-cancel path reverts to SKIPPED per §3.3.
    """
    if alloc["status"] != "RESERVED":
        return
    for li in alloc["line_items"]:
        product = db.products.get(li["product_id"])
        if product is not None:
            product["allocated_qty"] -= li["qty"]
            touch(product)
    wave = db.shipping_waves.get(alloc["wave_id"])
    if wave is not None:
        wave["reserved_count"] -= 1
        touch(wave)
    alloc["status"] = "RELEASED"
    touch(alloc)
    box = db.box_selections.get(alloc["box_selection_id"])
    if box is not None:
        box["decision"] = revert_decision
        box["allocation_id"] = None
        touch(box)


def commit_allocation(alloc):
    """RESERVED -> COMMITTED cascade on ship (PRD §3.9).

    Units physically depart: decrement BOTH on_hand_qty and allocated_qty.
    Creates a PACKED Shipment and finalizes the linked box selection.
    """
    if alloc["status"] != "RESERVED":
        return None
    for li in alloc["line_items"]:
        product = db.products.get(li["product_id"])
        if product is not None:
            product["on_hand_qty"] -= li["qty"]
            product["allocated_qty"] -= li["qty"]
            touch(product)
    alloc["status"] = "COMMITTED"
    touch(alloc)
    box = db.box_selections.get(alloc["box_selection_id"])
    if box is not None and box["decision"] != "FINALIZED":
        box["decision"] = "FINALIZED"
        touch(box)
    from common import new_record
    shipment = new_record({
        "allocation_id": alloc["id"],
        "wave_id": alloc["wave_id"],
        "subscription_id": alloc["subscription_id"],
        "status": "PACKED",
    })
    db.shipments[shipment["id"]] = shipment
    return shipment
