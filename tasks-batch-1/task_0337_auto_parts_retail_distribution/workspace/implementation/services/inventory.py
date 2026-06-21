"""Inventory accounting & the reorder auto-suggest cascade (PRD §2.6)."""
from __future__ import annotations

from db import db
from services.model import stamp_common, touch


def recompute_available(part: dict) -> None:
    """available_qty = on_hand_qty - reserved_qty (never negative)."""
    avail = part["on_hand_qty"] - part["reserved_qty"]
    part["available_qty"] = avail if avail > 0 else 0


def has_open_reorder(part_id: str) -> bool:
    """True if any reorder request for the part is SUGGESTED/ORDERED/PARTIALLY_RECEIVED."""
    for ro in db.reorder_requests.values():
        if ro["part_id"] == part_id and ro["status"] in (
            "SUGGESTED",
            "ORDERED",
            "PARTIALLY_RECEIVED",
        ):
            return True
    return False


def maybe_auto_suggest_reorder(part: dict) -> None:
    """Low-stock reorder cascade (PRD §2.6). Fires after an inventory decrement.

    Creates a SUGGESTED ReorderRequest when ALL hold:
      - part.stockable
      - part.status == ACTIVE
      - part.available_qty <= part.reorder_point  (inclusive comparator)
      - no existing reorder for the part in SUGGESTED/ORDERED/PARTIALLY_RECEIVED
    """
    if not part.get("stockable"):
        return
    if part.get("status") != "ACTIVE":
        return
    if part["available_qty"] > part["reorder_point"]:
        return
    if has_open_reorder(part["id"]):
        return
    ro = {
        "part_id": part["id"],
        "qty_ordered": part["reorder_qty"],
        "qty_received": 0,
        "status": "SUGGESTED",
    }
    stamp_common(ro)
    db.reorder_requests[ro["id"]] = ro


def decrement_on_hand(part: dict, qty: int, suggest: bool = True) -> None:
    """Debit on_hand, recompute available, and optionally fire the reorder cascade."""
    part["on_hand_qty"] -= qty
    if part["on_hand_qty"] < 0:
        part["on_hand_qty"] = 0
    recompute_available(part)
    touch(part)
    if suggest:
        maybe_auto_suggest_reorder(part)


def increment_on_hand(part: dict, qty: int) -> None:
    """Credit on_hand and recompute available (no reorder cascade — stock rises)."""
    part["on_hand_qty"] += qty
    recompute_available(part)
    touch(part)
