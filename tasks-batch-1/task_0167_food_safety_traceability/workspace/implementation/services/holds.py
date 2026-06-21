"""Hold-order issuance and resolution (PRD §3.6, §3.7).

Shared by the explicit POST /hold-orders endpoint and by the automatic
temperature-excursion hold raised from CCP-reading accrual (PRD §3.5).
"""
from __future__ import annotations

import db
from services.entities import base_fields, touch
from services.genealogy import covered_set, downstream_finished_closure

TERMINAL_LOT_STATUSES = {"REJECTED", "CONSUMED", "EXPIRED", "DESTROYED"}


def issue_hold(facility_id: str, target_lot_id: str, reason: str) -> dict:
    """Create an ACTIVE hold and freeze its covered set (cascade B)."""
    rec = base_fields(common=True)
    members = covered_set(target_lot_id)

    # Freeze every non-terminal covered lot.
    for lid in members:
        lot = db.lots.get(lid)
        if lot is None:
            continue
        if lot["status"] in TERMINAL_LOT_STATUSES:
            continue
        if lot["hold_status"] != "HELD":
            lot["hold_status"] = "HELD"
            touch(lot)

    rec.update({
        "facility_id": facility_id,
        "target_lot_id": target_lot_id,
        "reason": reason,
        "disposition": None,
        "held_lot_count": len(members),  # snapshot at issue time
        "status": "ACTIVE",
        "_covered_set": list(members),   # internal: pinned membership
    })
    db.hold_orders[rec["id"]] = rec
    return rec


def _other_active_hold_covers(lot_id: str, exclude_hold_id: str) -> bool:
    for h in db.hold_orders.values():
        if h["id"] == exclude_hold_id:
            continue
        if h["status"] != "ACTIVE":
            continue
        if lot_id in h.get("_covered_set", []):
            return True
    return False


def resolve_release(hold: dict) -> None:
    hold["disposition"] = "RELEASED"
    hold["status"] = "RELEASED"
    for lid in hold.get("_covered_set", []):
        lot = db.lots.get(lid)
        if lot is None:
            continue
        if lot["status"] in TERMINAL_LOT_STATUSES:
            # terminal lots are never re-mutated.
            continue
        new_status = "HELD" if _other_active_hold_covers(lid, hold["id"]) else "FREE"
        if lot["hold_status"] != new_status:
            lot["hold_status"] = new_status
            touch(lot)
    touch(hold)


def resolve_dispose(hold: dict) -> None:
    hold["disposition"] = "DISPOSED"
    hold["status"] = "DISPOSED"
    for lid in hold.get("_covered_set", []):
        lot = db.lots.get(lid)
        if lot is None:
            continue
        if lot["status"] in TERMINAL_LOT_STATUSES:
            continue
        lot["status"] = "DESTROYED"
        lot["available_qty"] = 0
        touch(lot)
    touch(hold)
