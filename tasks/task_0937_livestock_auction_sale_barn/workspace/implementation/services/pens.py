"""Pen occupancy, INV_PEN_OCCUPANCY (PRD 2.10, 3.1)."""
from store import db, touch

OCCUPYING_SALE_STATUSES = ("PENNED", "READY", "IN_RING", "SOLD", "NO_SALE")
OCCUPYING_CUSTODY_STATUSES = ("BARN", "BUYER_PEN")


def pen_head(pen_id):
    """Head standing in the pen right now (the invariant's own formula)."""
    total = 0
    for lot in db["lots"].values():
        if lot.get("pen_id") != pen_id:
            continue
        if lot["sale_status"] not in OCCUPYING_SALE_STATUSES:
            continue
        if lot["custody_status"] not in OCCUPYING_CUSTODY_STATUSES:
            continue
        total += lot["head_count"]
    return total


def recompute_pen(pen):
    """Recompute current_head and flip AVAILABLE <-> OCCUPIED as occupancy
    dictates. OUT_OF_SERVICE never flips automatically."""
    if pen is None:
        return None
    head = pen_head(pen["id"])
    changed = head != pen.get("current_head")
    pen["current_head"] = head
    if pen["status"] == "AVAILABLE" and head > 0:
        pen["status"] = "OCCUPIED"
        changed = True
    elif pen["status"] == "OCCUPIED" and head == 0:
        pen["status"] = "AVAILABLE"
        changed = True
    if changed:
        touch(pen)
    return pen


def recompute_pens(*pen_ids):
    seen = set()
    for pen_id in pen_ids:
        if not pen_id or pen_id in seen:
            continue
        seen.add(pen_id)
        recompute_pen(db["pens"].get(pen_id))
