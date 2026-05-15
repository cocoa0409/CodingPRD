"""DockSlot and SafetyInspection workflow (§3.5)."""

from datetime import timedelta
from flask import g

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_DOCK_SLOT_OVERLAP,
    ERR_RESOURCE_CONFLICT,
    ERR_OVERNIGHT_PERMIT_REQUIRED,
    ERR_SAFETY_INSPECTION_MISSING,
    ERR_FORBIDDEN,
)
from services.common import (
    stamp_create,
    stamp_create_appendonly,
    bump,
    check_occ,
    must_dict,
)


def _crosses_2200(start_dt, end_dt) -> bool:
    """Return True if [start_dt, end_dt) crosses 22:00 in its local clock.

    The PRD says 'crosses 22:00 local'. Without a stated timezone we evaluate
    in UTC (which is what we parse into); that is consistent with how the
    spec uses ISO 8601 throughout. Logic: walk each calendar day in [start,
    end) and check whether the slot contains that day's 22:00 instant.
    """
    if start_dt is None or end_dt is None:
        return False
    if start_dt >= end_dt:
        return False
    cur = start_dt
    while cur < end_dt:
        boundary = cur.replace(hour=22, minute=0, second=0, microsecond=0)
        if boundary < cur:
            # boundary already passed today; advance to next day
            boundary = boundary + timedelta(days=1)
        if start_dt <= boundary < end_dt:
            return True
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return False


def create_dock_slot(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    for f in ("dock_code", "window_kind", "start_at", "end_at", "allocation_id"):
        if f not in body or body[f] in (None, ""):
            raise AppError(ERR_INVALID_INPUT, f"Missing required field '{f}'.", 422)
    if body["window_kind"] not in ("MOVE_IN", "MOVE_OUT"):
        raise AppError(ERR_INVALID_INPUT, "Invalid window_kind.", 422)
    start_dt = clock.parse_iso(body["start_at"])
    end_dt = clock.parse_iso(body["end_at"])
    if start_dt is None or end_dt is None:
        raise AppError(ERR_INVALID_INPUT, "Invalid start_at/end_at.", 422)
    if start_dt >= end_dt:
        raise AppError(ERR_INVALID_INPUT, "start_at must be before end_at.", 422)
    allocation = db.allocations.get(body["allocation_id"])
    if allocation is None:
        raise AppError(ERR_NOT_FOUND, "Allocation not found.", 404)
    # Ownership: caller exhibitor must equal allocation.exhibitor_id.
    if g.role == "Exhibitor" and allocation["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Allocation not owned by exhibitor.", 403)
    # Allocation must be CONFIRMED.
    if allocation["status"] != "CONFIRMED":
        raise AppError(ERR_INVALID_STATE, "Allocation not CONFIRMED.", 409)
    # Exhibition status gating.
    if body["window_kind"] == "MOVE_IN" and ex["status"] != "SETUP":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in SETUP for MOVE_IN.", 409)
    if body["window_kind"] == "MOVE_OUT" and ex["status"] != "TEARDOWN":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in TEARDOWN for MOVE_OUT.", 409)

    crane_required = bool(body.get("crane_required") or False)
    forklift_required = bool(body.get("forklift_required") or False)
    overnight_permit = bool(body.get("overnight_permit") or False)

    # Overnight permit required when [start_at, end_at) crosses 22:00.
    if _crosses_2200(start_dt, end_dt) and not overnight_permit:
        raise AppError(ERR_OVERNIGHT_PERMIT_REQUIRED, "Overnight permit required.", 422)

    with db.LOCK:
        # Half-open overlap on same dock_code.
        for s in db.dock_slots.values():
            if s["status"] != "BOOKED":
                continue
            if s["dock_code"] != body["dock_code"]:
                continue
            s_start = clock.parse_iso(s["start_at"])
            s_end = clock.parse_iso(s["end_at"])
            if s_start is None or s_end is None:
                continue
            if start_dt < s_end and s_start < end_dt:
                raise AppError(ERR_DOCK_SLOT_OVERLAP, "Dock slot overlap.", 409)
        # Crane/forklift contention exhibition-wide per same start_at.
        for s in db.dock_slots.values():
            if s["status"] != "BOOKED":
                continue
            if s["exhibition_id"] != exhibition_id:
                continue
            s_start = clock.parse_iso(s["start_at"])
            if s_start != start_dt:
                continue
            if crane_required and s.get("crane_required"):
                raise AppError(ERR_RESOURCE_CONFLICT, "Crane already in use at this start_at.", 409)
            if forklift_required and s.get("forklift_required"):
                raise AppError(ERR_RESOURCE_CONFLICT, "Forklift already in use at this start_at.", 409)

        row = {
            "exhibition_id": exhibition_id,
            "dock_code": body["dock_code"],
            "window_kind": body["window_kind"],
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "allocation_id": body["allocation_id"],
            "crane_required": crane_required,
            "forklift_required": forklift_required,
            "overnight_permit": overnight_permit,
            "status": "BOOKED",
            "safety_inspection_passed": False,
        }
        stamp_create(row)
        db.dock_slots[row["id"]] = row
    return row


def complete_dock_slot(slot_id: str, body: dict) -> dict:
    slot = db.dock_slots.get(slot_id)
    if slot is None:
        raise AppError(ERR_NOT_FOUND, "Dock slot not found.", 404)
    if slot["status"] != "BOOKED":
        raise AppError(ERR_INVALID_STATE, "Dock slot not in BOOKED.", 409)
    if slot["window_kind"] == "MOVE_IN":
        # Need a BOOTH_MOVE_IN inspection with PASS.
        matching = [
            si for si in db.safety_inspections.values()
            if si.get("dock_slot_id") == slot_id
            and si.get("kind") == "BOOTH_MOVE_IN"
            and si.get("result") == "PASS"
        ]
        if not matching:
            raise AppError(
                ERR_SAFETY_INSPECTION_MISSING,
                "BOOTH_MOVE_IN PASS inspection required.",
                409,
            )
        # If overnight permit, inspection must be within last 8h of now.
        if slot.get("overnight_permit"):
            now_dt = clock.now()
            # Look for at least one matching inspection within 8h.
            recent = False
            for si in matching:
                cdt = clock.parse_iso(si.get("created_at"))
                if cdt is None:
                    continue
                if (now_dt - cdt).total_seconds() <= 8 * 3600:
                    recent = True
                    break
            if not recent:
                raise AppError(
                    ERR_SAFETY_INSPECTION_MISSING,
                    "Inspection not within the last 8 hours for overnight permit.",
                    409,
                )
        # Earlier MOVE_IN slots of the same allocation must all have safety_inspection_passed=true.
        for other in db.dock_slots.values():
            if other["id"] == slot_id:
                continue
            if other.get("allocation_id") != slot.get("allocation_id"):
                continue
            if other["window_kind"] != "MOVE_IN":
                continue
            other_start = clock.parse_iso(other.get("start_at"))
            this_start = clock.parse_iso(slot.get("start_at"))
            if other_start is None or this_start is None:
                continue
            if other_start < this_start and not other.get("safety_inspection_passed"):
                raise AppError(
                    ERR_SAFETY_INSPECTION_MISSING,
                    "Earlier MOVE_IN slot not yet inspected.",
                    409,
                )
    check_occ(slot, body)
    slot["status"] = "COMPLETED"
    slot["safety_inspection_passed"] = True
    bump(slot)
    return slot


def cancel_dock_slot(slot_id: str, body: dict) -> dict:
    slot = db.dock_slots.get(slot_id)
    if slot is None:
        raise AppError(ERR_NOT_FOUND, "Dock slot not found.", 404)
    if g.role == "Exhibitor":
        allocation = db.allocations.get(slot.get("allocation_id"))
        if allocation is None or allocation["exhibitor_id"] != g.user_id:
            raise AppError(ERR_FORBIDDEN, "Dock slot not owned by exhibitor.", 403)
    if slot["status"] != "BOOKED":
        raise AppError(ERR_INVALID_STATE, "Dock slot not in BOOKED.", 409)
    check_occ(slot, body)
    slot["status"] = "CANCELLED"
    slot["allocation_id"] = None
    bump(slot)
    return slot


# ---- Safety Inspection ----
def create_safety_inspection(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    kind = body.get("kind")
    result = body.get("result")
    inspector_id = body.get("inspector_id")
    if kind not in ("BOOTH_MOVE_IN", "PRE_OPEN", "OVERNIGHT"):
        raise AppError(ERR_INVALID_INPUT, "Invalid kind.", 422)
    if result not in ("PASS", "FAIL"):
        raise AppError(ERR_INVALID_INPUT, "Invalid result.", 422)
    if not inspector_id:
        raise AppError(ERR_INVALID_INPUT, "inspector_id is required.", 422)
    dock_slot_id = body.get("dock_slot_id")
    if kind == "BOOTH_MOVE_IN" and not dock_slot_id:
        raise AppError(ERR_INVALID_INPUT, "dock_slot_id required for BOOTH_MOVE_IN.", 422)
    if dock_slot_id and dock_slot_id not in db.dock_slots:
        raise AppError(ERR_NOT_FOUND, "Dock slot not found.", 404)
    row = {
        "exhibition_id": exhibition_id,
        "dock_slot_id": dock_slot_id,
        "kind": kind,
        "result": result,
        "inspector_id": inspector_id,
        "notes": body.get("notes"),
    }
    stamp_create_appendonly(row)
    db.safety_inspections[row["id"]] = row
    return row
