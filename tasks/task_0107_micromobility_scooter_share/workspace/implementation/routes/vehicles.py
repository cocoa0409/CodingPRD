"""Vehicle endpoints + lifecycle transitions + test-driving (PRD §3.1, §3.9).

POST /api/vehicles                          — PlatformAdmin
GET  /api/vehicles/{id}                      — PlatformAdmin, Rider, Technician
GET  /api/vehicles                           — PlatformAdmin, Rider, Technician
POST /api/vehicles/{id}/maintenance          — PlatformAdmin
POST /api/vehicles/{id}/return-to-service    — PlatformAdmin
POST /api/vehicles/{id}/retire               — PlatformAdmin
POST /api/_clock/set_current_utc             — PlatformAdmin (test-driving)
POST /api/_vehicles/{id}/set_battery         — PlatformAdmin (test-driving)
"""
from flask import Blueprint, request

import clock
import constants
import errors
from db import db, stamp_new, touch
from middleware import authenticate, require_role
from response import success
from services.mds import parse_iso
from services.vehicle import record_status_event, set_status
from util import (
    get_json_body, require_fields, require_enum, require_int,
    public, parse_pagination, paginate,
)

bp = Blueprint("vehicles", __name__)

VEHICLE_TYPES = {"SCOOTER", "EBIKE"}
VEHICLE_STATUSES = {"AVAILABLE", "RESERVED", "IN_USE", "LOW_BATTERY", "MAINTENANCE", "RETIRED"}


@bp.post("/api/vehicles")
def create_vehicle():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_json_body()
    require_fields(body, ["vehicle_type", "qr_code", "current_zone_id"])
    require_enum(body["vehicle_type"], VEHICLE_TYPES, "vehicle_type")
    if not isinstance(body["qr_code"], str) or body["qr_code"].strip() == "":
        raise errors.invalid_request("qr_code must be a non-empty string")

    battery = body.get("battery_pct", 100)
    require_int(battery, "battery_pct", minimum=0, maximum=100)

    if not isinstance(body["current_zone_id"], str) or body["current_zone_id"].strip() == "":
        raise errors.invalid_request("current_zone_id must be a non-empty string")

    # Uniqueness of qr_code across vehicles (PRD §3.1).
    for v in db.vehicles.values():
        if v["qr_code"] == body["qr_code"]:
            raise errors.invalid_request(f"qr_code {body['qr_code']} already exists")

    # current_zone_id is a body foreign key -> ERR_REFERENCE_NOT_FOUND when dangling.
    if body["current_zone_id"] not in db.zones:
        raise errors.reference_not_found("current_zone_id does not reference a zone")

    vehicle = {
        "vehicle_type": body["vehicle_type"],
        "qr_code": body["qr_code"],
        "battery_pct": battery,
        "current_zone_id": body["current_zone_id"],
        "status": "AVAILABLE",
    }
    stamp_new(vehicle)
    db.vehicles[vehicle["id"]] = vehicle
    # Seed the MDS status timeline with the registration event.
    record_status_event(vehicle)
    return success(public(vehicle), status=201)


@bp.get("/api/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider", "Technician"})
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise errors.not_found("Vehicle not found")
    return success(public(vehicle))


@bp.get("/api/vehicles")
def list_vehicles():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider", "Technician"})
    limit, offset = parse_pagination()

    rows = list(db.vehicles.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    current_zone_id = request.args.get("current_zone_id")
    if current_zone_id is not None:
        rows = [r for r in rows if r["current_zone_id"] == current_zone_id]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/vehicles/<vehicle_id>/maintenance")
def vehicle_maintenance(vehicle_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    vehicle = _require_vehicle(vehicle_id)
    # AVAILABLE or LOW_BATTERY -> MAINTENANCE (PRD §3.1).
    if vehicle["status"] not in ("AVAILABLE", "LOW_BATTERY"):
        raise errors.invalid_state("Vehicle cannot enter maintenance from its current state")
    set_status(vehicle, "MAINTENANCE")
    touch(vehicle)
    return success(public(vehicle))


@bp.post("/api/vehicles/<vehicle_id>/return-to-service")
def vehicle_return_to_service(vehicle_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    vehicle = _require_vehicle(vehicle_id)
    if vehicle["status"] != "MAINTENANCE":
        raise errors.invalid_state("Vehicle is not in maintenance")
    if vehicle["battery_pct"] < constants.MIN_START_BATTERY_PCT:
        raise errors.invalid_state("Vehicle battery too low to return to service")
    set_status(vehicle, "AVAILABLE")
    touch(vehicle)
    return success(public(vehicle))


@bp.post("/api/vehicles/<vehicle_id>/retire")
def vehicle_retire(vehicle_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    vehicle = _require_vehicle(vehicle_id)
    if vehicle["status"] != "MAINTENANCE":
        raise errors.invalid_state("Vehicle must be in maintenance to retire")
    set_status(vehicle, "RETIRED")
    touch(vehicle)
    return success(public(vehicle))


# --- Test-driving endpoints (PRD §3.9) --------------------------------------
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant")
    clock.set_clock(dt)
    # Endpoint output is null; data is an empty object per envelope contract.
    return success({})


@bp.post("/api/_vehicles/<vehicle_id>/set_battery")
def set_battery(vehicle_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    vehicle = _require_vehicle(vehicle_id)
    body = get_json_body()
    require_fields(body, ["battery_pct"])
    require_int(body["battery_pct"], "battery_pct", minimum=0, maximum=100)
    # Directly assign; does NOT change status and does NOT bump version (PRD §3.9).
    vehicle["battery_pct"] = body["battery_pct"]
    return success(public(vehicle))


def _require_vehicle(vehicle_id):
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise errors.not_found("Vehicle not found")
    return vehicle
