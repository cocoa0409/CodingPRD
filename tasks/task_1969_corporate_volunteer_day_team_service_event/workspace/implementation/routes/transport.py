"""Vehicle and TransportManifest endpoints (fleet, 30-minute turnaround rule)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_VEHICLE_NOT_FOUND,
    ERR_MANIFEST_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_MANIFEST_TRANSITION,
    ERR_MANIFEST_IN_PAST,
    ERR_VEHICLE_SCHEDULE_CONFLICT,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, bump, touch, refresh_event, ser_vehicle, ser_manifest, sort_entities
from timeutil import parse_datetime
from validate import req_string, req_int, req_present, check_range

bp = Blueprint("transport", __name__)

LC = ["LogisticsCoordinator"]


def load_manifest(manifest_id):
    m = db.manifests.get(manifest_id)
    if m is None:
        raise_err(ERR_MANIFEST_NOT_FOUND, "transport manifest not found")
    return m


@bp.post("/vehicles")
def create_vehicle():
    authenticate(LC)
    data = body()
    name = req_string(data, "name")
    capacity = req_int(data, "seat_capacity")
    check_range(capacity >= 1, "seat_capacity must be >= 1")
    v = mint()
    v.update({"name": name, "seat_capacity": capacity})
    db.vehicles[v["id"]] = v
    return success_object(ser_vehicle(v), 201)


@bp.get("/vehicles")
def list_vehicles():
    authenticate(["Any"])
    return success_list([ser_vehicle(v) for v in sort_entities(list(db.vehicles.values()))])


@bp.post("/transport-manifests")
def create_manifest():
    authenticate(LC)
    data = body()
    event_id = req_string(data, "event_id")
    vehicle_id = req_string(data, "vehicle_id")
    depart_raw = req_present(data, "depart_at")
    return_raw = req_present(data, "return_at")
    depart = parse_datetime(depart_raw, "depart_at")
    ret = parse_datetime(return_raw, "return_at")
    cost = req_int(data, "cost_cents")
    # body FK existence (step 5)
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise_err(ERR_VEHICLE_NOT_FOUND, "vehicle not found")
    # temporal (step 9)
    if depart <= db.now():
        raise_err(ERR_MANIFEST_IN_PAST, "depart_at must be strictly after the current clock")
    if ret <= depart:
        raise_err(ERR_VALIDATION, "return_at must be strictly after depart_at")
    # vehicle window conflict (step 10)
    if calc.vehicle_window_conflict(vehicle["id"], depart, ret):
        raise_err(ERR_VEHICLE_SCHEDULE_CONFLICT, "vehicle window conflicts under the 30-minute turnaround rule")
    # range (step 11)
    check_range(cost >= 0, "cost_cents must be >= 0")
    m = mint()
    m.update(
        {
            "event_id": ev["id"],
            "vehicle_id": vehicle["id"],
            "depart_at": depart_raw,
            "return_at": return_raw,
            "_depart": depart,
            "_return": ret,
            "cost_cents": cost,
            "status": "BOOKED",
        }
    )
    db.manifests[m["id"]] = m
    refresh_event(ev)
    return success_object(ser_manifest(m), 201)


@bp.get("/transport-manifests")
def list_manifests():
    authenticate(["Any"])
    items = list(db.manifests.values())
    for param in ("event_id", "vehicle_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [m for m in items if str(m.get(param)) == val]
    return success_list([ser_manifest(m) for m in sort_entities(items)])


@bp.get("/transport-manifests/<manifestId>")
def get_manifest(manifestId):
    authenticate(["Any"])
    return success_object(ser_manifest(load_manifest(manifestId)))


@bp.post("/transport-manifests/<manifestId>/confirm")
def confirm_manifest(manifestId):
    authenticate(LC)
    m = load_manifest(manifestId)
    if m["status"] != "BOOKED":
        raise_err(ERR_INVALID_MANIFEST_TRANSITION, "only a BOOKED manifest can be confirmed")
    m["status"] = "CONFIRMED"
    bump(m)
    ev = db.events.get(m["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_manifest(m))


@bp.post("/transport-manifests/<manifestId>/cancel")
def cancel_manifest(manifestId):
    authenticate(LC)
    m = load_manifest(manifestId)
    if m["status"] not in ("BOOKED", "CONFIRMED"):
        raise_err(ERR_INVALID_MANIFEST_TRANSITION, "manifest cannot be cancelled from its current status")
    m["status"] = "CANCELLED"
    bump(m)
    for r in db.registrations.values():
        if r["transport_manifest_id"] == m["id"]:
            r["transport_manifest_id"] = None
            touch(r)
    ev = db.events.get(m["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_manifest(m))
