"""shipment_allocation: FIFO lot allocation and backorder sweep."""

import db


def fifo_lots(release_id):
    lots = [
        lot for lot in db.inventory_lots.values()
        if lot["release_id"] == release_id and lot["on_hand_units"] > 0
    ]
    lots.sort(key=lambda l: (l["created_at"], l["receipt_seq"]))
    return lots


def try_allocate(shipment):
    """Attempt all-or-nothing FIFO allocation. Returns True if allocated."""
    lots = fifo_lots(shipment["release_id"])
    total_available = sum(l["on_hand_units"] for l in lots)
    if total_available < shipment["quantity"]:
        return False
    remaining = shipment["quantity"]
    allocations = []
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["on_hand_units"], remaining)
        if take > 0:
            lot["on_hand_units"] -= take
            lot["allocated_units"] += take
            lot["updated_at"] = db.timestamp_now()
            lot["version"] += 1
            allocations.append({"lot_id": lot["id"], "quantity": take})
            remaining -= take
    shipment["allocations"] = allocations
    shipment["status"] = "ALLOCATED"
    return True


def backorder_sweep(release_id):
    """Walk PLANNED shipments of the release in created_at ASC; allocate each
    that fully fits; skip ones that don't and keep scanning."""
    planned = [
        s for s in db.shipments.values()
        if s["release_id"] == release_id and s["status"] == "PLANNED"
    ]
    planned.sort(key=lambda s: s["created_at"])
    for shipment in planned:
        if try_allocate(shipment):
            shipment["updated_at"] = db.timestamp_now()
            shipment["version"] += 1
