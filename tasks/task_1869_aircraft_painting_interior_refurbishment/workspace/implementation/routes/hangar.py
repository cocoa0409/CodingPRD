"""HangarBay and HangarSlot endpoints."""
from flask import Blueprint, request

from db import STORE, now_dt
from domain import (new_entity, bump, get_or_404, by_created,
                    serialize_bay, serialize_slot)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_BAY_INACTIVE, ERR_SLOT_IN_PAST, ERR_SLOT_OVERLAP,
                    ERR_CREDIT_HOLD)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("hangar", __name__)


# --- HangarBay ---------------------------------------------------------------

@bp.post("/hangar-bays")
def create_bay():
    auth("CenterAdmin")
    data = get_body(required=True)
    name = field(data, "name", "str")
    daily_rate_cents = field(data, "daily_rate_cents", "int")
    bay = new_entity()
    bay.update({"name": name, "daily_rate_cents": daily_rate_cents,
                "status": "ACTIVE"})
    STORE.hangar_bays[bay["id"]] = bay
    return success(serialize_bay(bay), status=201)


@bp.get("/hangar-bays")
def list_bays():
    auth()
    items = by_created(list(STORE.hangar_bays.values()))
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(items, serialize_bay)


@bp.post("/hangar-bays/<bid>/deactivate")
def deactivate_bay(bid):
    auth("CenterAdmin")
    bay = get_or_404(STORE.hangar_bays, bid, "HangarBay")
    if bay["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE bay can be deactivated")
    open_slot = any(s["bay_id"] == bid and s["status"] in ("BOOKED", "ACTIVE")
                    for s in STORE.hangar_slots.values())
    if open_slot:
        raise ApiError(ERR_BAY_INACTIVE, 409,
                       "Bay holds BOOKED or ACTIVE slots")
    bay["status"] = "INACTIVE"
    bump(bay)
    return success(serialize_bay(bay))


# --- HangarSlot ----------------------------------------------------------------

@bp.post("/hangar-slots")
def create_slot():
    auth("ProgramManager")
    data = get_body(required=True)
    bay_id = field(data, "bay_id", "str")
    program_id = field(data, "program_id", "str")
    start_at = field(data, "start_at", "datetime")
    end_at = field(data, "end_at", "datetime")
    bay = STORE.hangar_bays.get(bay_id)
    if bay is None:
        raise ref_integrity("bay_id does not reference an existing hangar bay")
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] not in ("QUOTED", "BOOKED"):
        raise invalid_state(
            "Slots may be booked only while the program is QUOTED or BOOKED")
    if bay["status"] != "ACTIVE":
        raise ApiError(ERR_BAY_INACTIVE, 409, "Bay is INACTIVE")
    clock = now_dt()
    if start_at < clock or start_at >= end_at:
        raise ApiError(ERR_SLOT_IN_PAST, 409,
                       "Slot start_at must be >= the logical clock and < end_at")
    for s in STORE.hangar_slots.values():
        if s["bay_id"] != bay_id or s["status"] not in ("BOOKED", "ACTIVE"):
            continue
        # Half-open overlap: s.start < new.end AND new.start < s.end.
        if s["start_at"] < end_at and start_at < s["end_at"]:
            raise ApiError(ERR_SLOT_OVERLAP, 409,
                           "Slot overlaps an existing BOOKED/ACTIVE slot on this bay")
    cust = STORE.customers.get(prog["customer_id"])
    if cust is None or cust["credit_status"] != "GOOD_STANDING":
        raise ApiError(ERR_CREDIT_HOLD, 402, "Customer is on CREDIT_HOLD")
    slot = new_entity()
    slot.update({
        "bay_id": bay_id,
        "program_id": program_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
    })
    STORE.hangar_slots[slot["id"]] = slot
    return success(serialize_slot(slot), status=201)


@bp.get("/hangar-slots/<sid>")
def get_slot(sid):
    auth()
    slot = get_or_404(STORE.hangar_slots, sid, "HangarSlot")
    return success(serialize_slot(slot))


@bp.get("/hangar-slots")
def list_slots():
    auth()
    items = by_created(list(STORE.hangar_slots.values()))
    for key in ("bay_id", "program_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [s for s in items if s[key] == value]
    return paginate(items, serialize_slot)


@bp.post("/hangar-slots/<sid>/activate")
def activate_slot(sid):
    auth("ProgramManager")
    slot = get_or_404(STORE.hangar_slots, sid, "HangarSlot")
    if slot["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED slot can be activated")
    prog = STORE.programs[slot["program_id"]]
    if prog["status"] not in ("BOOKED", "INDUCTED"):
        raise invalid_state(
            "Slot activation requires the program to be BOOKED or INDUCTED")
    clock = now_dt()
    if clock >= slot["end_at"]:
        raise ApiError(ERR_SLOT_IN_PAST, 409, "The slot window has passed")
    if clock < slot["start_at"]:
        raise invalid_state("The slot window has not started")
    slot["status"] = "ACTIVE"
    bump(slot)
    return success(serialize_slot(slot))


@bp.post("/hangar-slots/<sid>/release")
def release_slot(sid):
    auth("ProgramManager")
    slot = get_or_404(STORE.hangar_slots, sid, "HangarSlot")
    if slot["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE slot can be released")
    slot["status"] = "RELEASED"
    bump(slot)
    return success(serialize_slot(slot))


@bp.post("/hangar-slots/<sid>/cancel")
def cancel_slot(sid):
    auth("ProgramManager")
    slot = get_or_404(STORE.hangar_slots, sid, "HangarSlot")
    if slot["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED slot can be cancelled")
    slot["status"] = "CANCELLED"
    bump(slot)
    return success(serialize_slot(slot))
