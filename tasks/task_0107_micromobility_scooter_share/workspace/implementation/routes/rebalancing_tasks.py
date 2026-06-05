"""RebalancingTask endpoints (PRD §3.7).

POST /api/rebalancing-tasks                 — PlatformAdmin (OCC on vehicle)
GET  /api/rebalancing-tasks/{id}            — PlatformAdmin, Technician
GET  /api/rebalancing-tasks                  — PlatformAdmin, Technician
POST /api/rebalancing-tasks/{id}/assign      — PlatformAdmin (buffered overlap)
POST /api/rebalancing-tasks/{id}/unassign    — PlatformAdmin
POST /api/rebalancing-tasks/{id}/complete    — Technician (owner only)
POST /api/rebalancing-tasks/{id}/cancel      — PlatformAdmin
"""
from flask import Blueprint, request

import constants
import errors
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_technician_owner
from response import success
from services.mds import parse_iso
from services.vehicle import set_status
from util import (
    get_json_body, require_fields, require_enum, require_int, require_string,
    public, parse_pagination, paginate,
)

bp = Blueprint("rebalancing_tasks", __name__)

TASK_TYPES = {"MOVE", "SWAP"}


@bp.post("/api/rebalancing-tasks")
def create_task():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_json_body()
    require_fields(body, ["vehicle_id", "task_type", "window_start", "window_end", "expected_vehicle_version"])
    require_string(body["vehicle_id"], "vehicle_id")
    require_enum(body["task_type"], TASK_TYPES, "task_type")

    # Body FK references (priority 5) precede window/field-shape/OCC.
    vehicle = db.vehicles.get(body["vehicle_id"])
    if vehicle is None:
        raise errors.reference_not_found("vehicle_id does not reference a vehicle")

    target_zone_id = body.get("target_zone_id")
    if body["task_type"] == "MOVE":
        if not isinstance(target_zone_id, str) or target_zone_id.strip() == "":
            raise errors.invalid_request("target_zone_id is required for a MOVE task")
        if target_zone_id not in db.zones:
            raise errors.reference_not_found("target_zone_id does not reference a zone")
    else:
        # SWAP: target_zone_id must be null.
        target_zone_id = None

    # Window temporal validity (priority 13): window_end strictly after start.
    ws = parse_iso(body["window_start"])
    we = parse_iso(body["window_end"])
    if ws is None or we is None:
        raise errors.invalid_request("window_start/window_end must be ISO 8601 instants")
    if not (we > ws):
        raise errors.ApiError(
            errors.ERR_INVALID_WINDOW, 422,
            "window_end must be strictly after window_start",
        )

    # Field-shape (priority 15): expected_vehicle_version must be an integer.
    require_int(body["expected_vehicle_version"], "expected_vehicle_version")

    # OCC (priority 16): expected_vehicle_version must equal current version.
    if body["expected_vehicle_version"] != vehicle["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_VEHICLE_VERSION, 412,
            "expected_vehicle_version does not match the vehicle's current version",
        )

    task = {
        "vehicle_id": vehicle["id"],
        "technician_id": None,
        "task_type": body["task_type"],
        "target_zone_id": target_zone_id,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "OPEN",
    }
    stamp_new(task)
    db.rebalancing_tasks[task["id"]] = task

    # A successful create increments the vehicle's version (PRD §2.7).
    touch(vehicle)
    return success(public(task), status=201)


@bp.get("/api/rebalancing-tasks/<task_id>")
def get_task(task_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Technician"})
    task = _require_task(task_id)
    return success(public(task))


@bp.get("/api/rebalancing-tasks")
def list_tasks():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Technician"})
    limit, offset = parse_pagination()

    rows = list(db.rebalancing_tasks.values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    technician_id = request.args.get("technician_id")
    if technician_id is not None:
        rows = [r for r in rows if r["technician_id"] == technician_id]
    target_zone_id = request.args.get("target_zone_id")
    if target_zone_id is not None:
        rows = [r for r in rows if r["target_zone_id"] == target_zone_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/rebalancing-tasks/<task_id>/assign")
def assign_task(task_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    task = _require_task(task_id)

    body = get_json_body()
    require_fields(body, ["technician_id"])
    require_string(body["technician_id"], "technician_id")

    if task["status"] != "OPEN":
        raise errors.invalid_state("Task is not OPEN")

    tech = db.technicians.get(body["technician_id"])
    if tech is None:
        raise errors.reference_not_found("technician_id does not reference a technician")

    # Named technician must be on shift (PRD §3.7).
    if not tech["on_shift"]:
        raise errors.invalid_request("Technician is not on shift")

    # Buffered no-overlap rule (priority 11): the task's window widened by
    # TASK_BUFFER_SECONDS on each side (closed interval) must not overlap the
    # identically buffered window of any other ASSIGNED task for the same tech.
    if _has_buffered_overlap(task, tech["id"]):
        raise errors.ApiError(
            errors.ERR_TECH_WINDOW_OVERLAP, 409,
            "Buffered window overlaps another assigned task for this technician",
        )

    task["technician_id"] = tech["id"]
    task["status"] = "ASSIGNED"
    touch(task)
    return success(public(task))


@bp.post("/api/rebalancing-tasks/<task_id>/unassign")
def unassign_task(task_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    task = _require_task(task_id)
    if task["status"] != "ASSIGNED":
        raise errors.invalid_state("Task is not ASSIGNED")
    task["technician_id"] = None
    task["status"] = "OPEN"
    touch(task)
    return success(public(task))


@bp.post("/api/rebalancing-tasks/<task_id>/complete")
def complete_task(task_id):
    role, user_id = authenticate()
    require_role(role, {"Technician"})
    task = _require_task(task_id)

    # Owner-only: the acting technician must be the task's technician (PRD §2.1).
    require_technician_owner(role, user_id, task["technician_id"])

    if task["status"] != "ASSIGNED":
        raise errors.invalid_state("Task is not ASSIGNED")

    vehicle = db.vehicles.get(task["vehicle_id"])
    if task["task_type"] == "SWAP":
        if vehicle["status"] != "LOW_BATTERY":
            raise errors.invalid_state("Vehicle is not LOW_BATTERY for a SWAP completion")
        vehicle["battery_pct"] = 100
        set_status(vehicle, "AVAILABLE")
        touch(vehicle)
    else:  # MOVE
        if vehicle["status"] != "AVAILABLE":
            raise errors.invalid_state("Vehicle is not AVAILABLE for a MOVE completion")
        vehicle["current_zone_id"] = task["target_zone_id"]
        touch(vehicle)

    task["status"] = "COMPLETED"
    touch(task)
    return success(public(task))


@bp.post("/api/rebalancing-tasks/<task_id>/cancel")
def cancel_task(task_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    task = _require_task(task_id)
    if task["status"] not in ("OPEN", "ASSIGNED"):
        raise errors.invalid_state("Task is not OPEN or ASSIGNED")
    # Cancelling an assigned task clears its technician_id (PRD §3.7).
    task["technician_id"] = None
    task["status"] = "CANCELLED"
    touch(task)
    return success(public(task))


def _has_buffered_overlap(task, technician_id):
    """True if the buffered closed window of `task` overlaps any other ASSIGNED
    task's buffered closed window for the same technician (PRD §3.7)."""
    ws = parse_iso(task["window_start"])
    we = parse_iso(task["window_end"])
    buf = constants.TASK_BUFFER_SECONDS
    new_lo = ws.timestamp() - buf
    new_hi = we.timestamp() + buf
    for other in db.rebalancing_tasks.values():
        if other["id"] == task["id"]:
            continue
        if other["status"] != "ASSIGNED":
            continue
        if other["technician_id"] != technician_id:
            continue
        ows = parse_iso(other["window_start"])
        owe = parse_iso(other["window_end"])
        o_lo = ows.timestamp() - buf
        o_hi = owe.timestamp() + buf
        # Closed intervals overlap iff new_lo <= o_hi and o_lo <= new_hi.
        if new_lo <= o_hi and o_lo <= new_hi:
            return True
    return False


def _require_task(task_id):
    task = db.rebalancing_tasks.get(task_id)
    if task is None:
        raise errors.not_found("Rebalancing task not found")
    return task
