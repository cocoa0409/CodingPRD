"""Instructors, simulator slots, and the append-only cost ledger."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    bump, get_instructor, get_ledger_entry, get_slot, ser_instructor,
    ser_ledger_entry, ser_simulator_slot, stamp_new,
)
from util import (
    get_body, is_int, pagination_params, req_str, req_ts, sort_rows,
    success_list, success_object,
)

bp = Blueprint("resources", __name__)

INSTRUCTOR_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "CheckAirman", "SystemAdmin")
SLOT_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")
LEDGER_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")
INSTRUCTOR_TYPES = ("GROUND", "SIMULATOR", "CHECK_AIRMAN")


# ---- Instructors --------------------------------------------------------------------

@bp.post("/instructors")
def create_instructor():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    instructor_type = body.get("instructor_type")
    daily_max_sessions = body.get("daily_max_sessions")
    if instructor_type not in INSTRUCTOR_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "instructor_type must be one of %s" % ", ".join(INSTRUCTOR_TYPES))
    if not is_int(daily_max_sessions) or daily_max_sessions < 1:
        raise ApiError("ERR_INVALID_REQUEST", "daily_max_sessions must be an integer >= 1")
    instructor = stamp_new({
        "full_name": full_name,
        "instructor_type": instructor_type,
        "daily_max_sessions": daily_max_sessions,
    })
    store.instructors[instructor["id"]] = instructor
    return success_object(ser_instructor(instructor), 201)


@bp.get("/instructors")
def list_instructors():
    require_roles(*INSTRUCTOR_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.instructors.values())
    instructor_type = request.args.get("instructor_type")
    if instructor_type is not None:
        rows = [i for i in rows if i["instructor_type"] == instructor_type]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_instructor(i) for i in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/instructors/<iid>")
def read_instructor(iid):
    require_roles(*INSTRUCTOR_READ_ROLES)
    return success_object(ser_instructor(get_instructor(iid)))


# ---- Simulator slots -----------------------------------------------------------------

@bp.post("/simulator-slots")
def create_slot():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    equipment_id = req_str(body, "equipment_id")
    start_at = req_ts(body, "start_at")
    end_at = req_ts(body, "end_at")
    from services import get_equipment
    get_equipment(equipment_id)
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    slot = stamp_new({
        "equipment_id": equipment_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "AVAILABLE",
    })
    store.simulator_slots[slot["id"]] = slot
    return success_object(ser_simulator_slot(slot), 201)


@bp.get("/simulator-slots")
def list_slots():
    require_roles(*SLOT_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.simulator_slots.values())
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    if equipment_id is not None:
        rows = [s for s in rows if s["equipment_id"] == equipment_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_simulator_slot(s) for s in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/simulator-slots/<sid>")
def read_slot(sid):
    require_roles(*SLOT_READ_ROLES)
    return success_object(ser_simulator_slot(get_slot(sid)))


@bp.post("/simulator-slots/<sid>/maintenance")
def toggle_slot_maintenance(sid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    slot = get_slot(sid)
    if slot["status"] == "AVAILABLE":
        # Blocked while any SCHEDULED event sits inside the window.
        if any(ev["simulator_slot_id"] == sid and ev["status"] == "SCHEDULED"
               for ev in store.training_events.values()):
            raise ApiError("ERR_SLOT_HAS_BOOKINGS",
                           "Slot has SCHEDULED bookings inside the window")
        slot["status"] = "MAINTENANCE"
    else:
        slot["status"] = "AVAILABLE"  # return leg carries no booking check
    bump(slot)
    return success_object(ser_simulator_slot(slot))


# ---- Cost ledger (read-only; entries are created exclusively by cascades) -----------

@bp.get("/cost-ledger")
def list_ledger():
    require_roles(*LEDGER_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.cost_ledger.values())
    applicant_id = request.args.get("applicant_id")
    enrollment_id = request.args.get("enrollment_id")
    entry_type = request.args.get("entry_type")
    if applicant_id is not None:
        rows = [e for e in rows if e["applicant_id"] == applicant_id]
    if enrollment_id is not None:
        rows = [e for e in rows if e["enrollment_id"] == enrollment_id]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_ledger_entry(e) for e in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/cost-ledger/<lid>")
def read_ledger_entry(lid):
    require_roles(*LEDGER_READ_ROLES)
    return success_object(ser_ledger_entry(get_ledger_entry(lid)))
