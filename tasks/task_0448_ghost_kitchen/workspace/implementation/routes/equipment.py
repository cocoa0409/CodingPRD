"""Equipment endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from validation import get_body, require_str, require_enum, optional_int

bp = Blueprint("equipment", __name__)

EQUIPMENT_TYPES = {"FRYER", "OVEN", "GRILL", "PREP_STATION"}


def _check_stall_owner(role, user_id, stall_id):
    if role == "StallOperator" and user_id != stall_id:
        raise errors.forbidden()


@bp.route("/equipment", methods=["POST"])
def create_equipment():
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    body = get_body()
    stall_id = require_str(body, "stall_id")
    equipment_type = require_enum(body, "equipment_type", EQUIPMENT_TYPES)
    buffer_min = optional_int(body, "turnaround_buffer_minutes", 0)
    with store.lock:
        stall = get_or_404(store.stalls, stall_id)
        # Ownership: StallOperator must own the targeted stall.
        _check_stall_owner(role, user_id, stall_id)
        if buffer_min < 0:
            raise errors.invalid_request("turnaround_buffer_minutes must be >= 0.")
        rec = new_entity("Equipment", {
            "stall_id": stall_id,
            "equipment_type": equipment_type,
            "turnaround_buffer_minutes": buffer_min,
            "status": "AVAILABLE",
        })
        store.equipment[rec["id"]] = rec
        # Derived-field reconciliation: owning stall equipment_count += 1.
        stall["equipment_count"] += 1
        touch(stall)
        return object_response(serialize(rec), 201)


@bp.route("/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        rec = get_or_404(store.equipment, eid)
        return object_response(serialize(rec))


@bp.route("/equipment/<eid>/maintenance", methods=["POST"])
def equipment_maintenance(eid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.equipment, eid)
        _check_stall_owner(role, user_id, rec["stall_id"])
        if rec["status"] != "AVAILABLE":
            raise errors.invalid_state()
        rec["status"] = "MAINTENANCE"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/equipment/<eid>/restore", methods=["POST"])
def equipment_restore(eid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.equipment, eid)
        _check_stall_owner(role, user_id, rec["stall_id"])
        if rec["status"] != "MAINTENANCE":
            raise errors.invalid_state()
        rec["status"] = "AVAILABLE"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/equipment/<eid>/retire", methods=["POST"])
def equipment_retire(eid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.equipment, eid)
        _check_stall_owner(role, user_id, rec["stall_id"])
        if rec["status"] != "AVAILABLE":
            raise errors.invalid_state()
        # No HELD booking on this unit.
        for b in store.bookings.values():
            if b["equipment_id"] == eid and b["status"] == "HELD":
                raise errors.invalid_state()
        rec["status"] = "RETIRED"
        touch(rec)
        # Derived-field reconciliation: owning stall equipment_count -= 1.
        stall = store.stalls.get(rec["stall_id"])
        if stall is not None:
            stall["equipment_count"] -= 1
            touch(stall)
        return object_response(serialize(rec))


@bp.route("/equipment/<eid>/bookings", methods=["GET"])
def list_equipment_bookings(eid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        get_or_404(store.equipment, eid)
        recs = [b for b in store.bookings.values() if b["equipment_id"] == eid]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)
