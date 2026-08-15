"""Drone endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import serialize_drone, touch, ground_drone_cascade

bp = Blueprint("drones", __name__)


def _get_drone(drone_id):
    d = DB.drones.get(drone_id)
    if d is None:
        raise errors.not_found("ERR_DRONE_NOT_FOUND", "drone not found")
    return d


@bp.route("/api/drones", methods=["POST"])
def create_drone():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["serial_number", "model"])
    require_role("FleetManager")
    serial = V.req_string(body, "serial_number")
    model = V.req_string(body, "model")
    charge = body.get("charge_pct", 100)
    cycles = body.get("battery_cycle_count", 0)
    if isinstance(charge, bool) or not isinstance(charge, int) or not (0 <= charge <= 100):
        raise errors.validation("charge_pct must be an integer within [0, 100]")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 0:
        raise errors.validation("battery_cycle_count must be an integer >= 0")

    for did in DB.insertion_order["drones"]:
        if DB.drones[did]["serial_number"] == serial:
            raise errors.conflict("ERR_DUPLICATE_SERIAL", "serial_number already registered")

    did = new_id()
    ts = wall_created_at()
    drone = {
        "id": did, "serial_number": serial, "model": model,
        "charge_pct": charge, "battery_cycle_count": cycles,
        "status": "AVAILABLE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.drones[did] = drone
    DB.insertion_order["drones"].append(did)
    return success_object(serialize_drone(drone), 201)


@bp.route("/api/drones/<droneId>", methods=["GET"])
def get_drone(droneId):
    get_auth()
    return success_object(serialize_drone(_get_drone(droneId)))


@bp.route("/api/drones", methods=["GET"])
def list_drones():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    status = V.opt_string(request.args, "status")
    items = [DB.drones[i] for i in DB.insertion_order["drones"]]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_drone(d) for d in page], limit, offset, total)


@bp.route("/api/drones/<droneId>/ground", methods=["POST"])
def ground_drone(droneId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("SafetyOfficer")
    drone = _get_drone(droneId)
    if drone["status"] not in ("AVAILABLE", "RESERVED", "IN_MAINTENANCE"):
        raise errors.conflict("ERR_INVALID_STATE", "drone cannot be grounded from its current state")
    was_reserved = drone["status"] == "RESERVED"
    drone["status"] = "GROUNDED"
    touch(drone)
    if was_reserved:
        ground_drone_cascade(drone)
    return success_object(serialize_drone(drone))


@bp.route("/api/drones/<droneId>/release", methods=["POST"])
def release_drone(droneId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("SafetyOfficer")
    drone = _get_drone(droneId)
    if drone["status"] not in ("IN_MAINTENANCE", "GROUNDED"):
        raise errors.conflict("ERR_INVALID_STATE", "drone must be IN_MAINTENANCE or GROUNDED to release")
    drone["status"] = "AVAILABLE"
    touch(drone)
    return success_object(serialize_drone(drone))


@bp.route("/api/drones/<droneId>/maintain", methods=["POST"])
def maintain_drone(droneId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("FleetManager")
    drone = _get_drone(droneId)
    if drone["status"] != "AVAILABLE":
        raise errors.conflict("ERR_INVALID_STATE", "drone must be AVAILABLE to enter maintenance")
    drone["status"] = "IN_MAINTENANCE"
    touch(drone)
    return success_object(serialize_drone(drone))


@bp.route("/api/drones/<droneId>/retire", methods=["POST"])
def retire_drone(droneId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("FleetManager")
    drone = _get_drone(droneId)
    if drone["status"] not in ("AVAILABLE", "IN_MAINTENANCE", "GROUNDED"):
        raise errors.conflict("ERR_INVALID_STATE", "drone cannot be retired from its current state")
    drone["status"] = "RETIRED"
    touch(drone)
    return success_object(serialize_drone(drone))
