"""Turn tasks: start, submit-for-inspection, inspect (with rework
escalation), cancel (PRD 3.6)."""
from flask import Blueprint

from authz import ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, require_roles
from db import store
from errors import ApiError, invalid_state
from respond import success
from serialize import ser_turn_task
from store_ops import get_or_404, json_body, opt_field, req_enum, touch

bp = Blueprint("turns", __name__)

WORK_ROLES = [HOUSEKEEPING, ADMIN]


@bp.route("/turn-tasks/<tid>", methods=["GET"])
def get_turn_task(tid):
    require_roles([ADMIN, FACILITIES, HOUSEKEEPING, FINANCE])
    return success(ser_turn_task(get_or_404(store.turn_tasks, tid)))


@bp.route("/turn-tasks/<tid>/start", methods=["POST"])
def start_turn_task(tid):
    require_roles(WORK_ROLES)
    t = get_or_404(store.turn_tasks, tid)
    if t["status"] not in ("SCHEDULED", "FAILED"):
        raise invalid_state("Turn task must be SCHEDULED or FAILED to start")
    room = store.rooms[t["room_id"]]
    if room["status"] not in ("NEEDS_TURN", "IN_TURN"):
        raise invalid_state("Room must be NEEDS_TURN or IN_TURN to start the task")
    if room["status"] == "NEEDS_TURN":
        room["status"] = "IN_TURN"
        touch(room)
    t["status"] = "IN_PROGRESS"
    touch(t)
    return success(ser_turn_task(t))


@bp.route("/turn-tasks/<tid>/submit-for-inspection", methods=["POST"])
def submit_for_inspection(tid):
    require_roles(WORK_ROLES)
    t = get_or_404(store.turn_tasks, tid)
    if t["status"] != "IN_PROGRESS":
        raise invalid_state("Turn task must be IN_PROGRESS to submit for inspection")
    t["status"] = "READY_FOR_INSPECTION"
    touch(t)
    return success(ser_turn_task(t))


@bp.route("/turn-tasks/<tid>/inspect", methods=["POST"])
def inspect_turn_task(tid):
    uid, role = require_roles(WORK_ROLES)
    t = get_or_404(store.turn_tasks, tid)
    # Priority 3: rework escalation — once rework_count has reached two, only
    # a ConferenceServicesAdmin may inspect.
    if role == HOUSEKEEPING and t["rework_count"] >= 2:
        raise ApiError("ERR_TURN_REWORK_ESCALATION", 403,
                       "Turn task rework_count >= 2 restricts inspection to ConferenceServicesAdmin")
    data = json_body()
    outcome = req_enum(data, "outcome", ("PASS", "FAIL"))
    note = opt_field(data, "note")
    if note is not None and not isinstance(note, str):
        from errors import invalid_request
        raise invalid_request("note must be a string")
    if t["status"] != "READY_FOR_INSPECTION":
        raise invalid_state("Turn task must be READY_FOR_INSPECTION to inspect")
    if note is not None:
        t["inspector_note"] = note
    if outcome == "PASS":
        t["status"] = "PASSED"
        room = store.rooms[t["room_id"]]
        if room["status"] == "IN_TURN":
            room["status"] = "READY"
        room["active_turn_task_id"] = None
        touch(room)
        building = store.buildings[room["building_id"]]
        building["scheduled_turn_count"] -= 1
        touch(building)
    else:
        t["status"] = "FAILED"
        t["rework_count"] += 1
    touch(t)
    return success(ser_turn_task(t))


@bp.route("/turn-tasks/<tid>/cancel", methods=["POST"])
def cancel_turn_task(tid):
    require_roles([ADMIN])
    t = get_or_404(store.turn_tasks, tid)
    if t["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED turn task may be cancelled")
    t["status"] = "CANCELLED"
    room = store.rooms[t["room_id"]]
    if room["status"] == "NEEDS_TURN":
        room["status"] = "READY"
    room["active_turn_task_id"] = None
    touch(room)
    building = store.buildings[room["building_id"]]
    building["scheduled_turn_count"] -= 1
    touch(building)
    touch(t)
    return success(ser_turn_task(t))
