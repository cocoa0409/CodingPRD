"""Dock door endpoints (PRD section 3.5)."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_invalid_state, err_terminal_closed)
from middleware import require_roles
from response import success, success_list
from routes.common import (as_enum, as_int, body_json, get_path, new_record,
                           paginate, resolve_fk, ser_door, touch)
from services.calculations import DOOR_KINDS

bp = Blueprint("doors", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor")


def _door_in_use(door):
    """No-active-user precondition shared by release and take-out-of-service."""
    batch_active = any(
        b["inbound_door_id"] == door["id"] and b["status"] in ("OPEN", "CLOSED")
        for b in db.store["sortation_batches"].values())
    trailer_active = any(
        t["outbound_door_id"] == door["id"] and t["posture"] in ("LOADING", "READY", "SEALED")
        for t in db.store["trailers"].values())
    return batch_active or trailer_active


@bp.route("/ltl/dock-doors", methods=["POST"])
@require_roles("DockSupervisor")
def create_door():
    body = body_json()
    terminal = resolve_fk("terminals", body.get("terminal_id"), "terminal_id")
    door_number = as_int(body, "door_number", minimum=1)
    door_kind = as_enum(body, "door_kind", DOOR_KINDS)
    if any(d["terminal_id"] == terminal["id"] and d["door_number"] == door_number
           for d in db.store["dock_doors"].values()):
        raise err_invalid_request("(terminal_id, door_number) must be unique")
    rec = new_record({
        "terminal_id": terminal["id"], "door_number": door_number,
        "door_kind": door_kind, "status": "AVAILABLE",
    })
    db.store["dock_doors"][rec["id"]] = rec
    return success(ser_door(rec), 201)


@bp.route("/ltl/dock-doors", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_doors():
    items = list(db.store["dock_doors"].values())
    for param in ("terminal_id", "door_kind", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [d for d in items if d.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_door(d) for d in page], total, limit, offset)


@bp.route("/ltl/dock-doors/<doorId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_door(doorId):
    return success(ser_door(get_path("dock_doors", doorId)))


@bp.route("/ltl/dock-doors/<doorId>/reserve", methods=["POST"])
@require_roles("DockSupervisor")
def reserve_door(doorId):
    door = get_path("dock_doors", doorId)
    if door["status"] != "AVAILABLE":
        raise err_invalid_state("Only an AVAILABLE door can be reserved")
    # Priority 16: closed-terminal guard.
    terminal = db.store["terminals"].get(door["terminal_id"])
    if terminal is not None and terminal["status"] == "CLOSED":
        raise err_terminal_closed("Cannot reserve a door at a CLOSED terminal")
    door["status"] = "RESERVED"
    touch(door)
    return success(ser_door(door))


@bp.route("/ltl/dock-doors/<doorId>/occupy", methods=["POST"])
@require_roles("DockSupervisor")
def occupy_door(doorId):
    door = get_path("dock_doors", doorId)
    if door["status"] != "RESERVED":
        raise err_invalid_state("Only a RESERVED door can be occupied")
    door["status"] = "OCCUPIED"
    touch(door)
    return success(ser_door(door))


@bp.route("/ltl/dock-doors/<doorId>/release", methods=["POST"])
@require_roles("DockSupervisor")
def release_door(doorId):
    door = get_path("dock_doors", doorId)
    if door["status"] != "OCCUPIED":
        raise err_invalid_state("Only an OCCUPIED door can be released")
    if _door_in_use(door):
        raise err_invalid_state(
            "Door cannot be released while an active batch or trailer uses it")
    door["status"] = "AVAILABLE"
    touch(door)
    return success(ser_door(door))


@bp.route("/ltl/dock-doors/<doorId>/take-out-of-service", methods=["POST"])
@require_roles("DockSupervisor")
def take_out_of_service(doorId):
    door = get_path("dock_doors", doorId)
    if door["status"] not in ("AVAILABLE", "RESERVED", "OCCUPIED"):
        raise err_invalid_state("Door cannot be taken out of service from its current state")
    if _door_in_use(door):
        raise err_invalid_state(
            "Door cannot be taken out of service while an active batch or trailer uses it")
    door["status"] = "OUT_OF_SERVICE"
    touch(door)
    return success(ser_door(door))


@bp.route("/ltl/dock-doors/<doorId>/return-to-service", methods=["POST"])
@require_roles("DockSupervisor")
def return_to_service(doorId):
    door = get_path("dock_doors", doorId)
    if door["status"] != "OUT_OF_SERVICE":
        raise err_invalid_state("Only an OUT_OF_SERVICE door can be returned to service")
    door["status"] = "AVAILABLE"
    touch(door)
    return success(ser_door(door))
