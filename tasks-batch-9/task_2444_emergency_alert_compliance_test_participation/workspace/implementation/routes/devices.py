"""EASDevice endpoints (PRD 3.2)."""

from flask import Blueprint, request

import clock
import serializers
import store
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from store import base_row, db, mark_created, touch
from validators import (
    DEVICE_ROLES,
    get_device,
    get_station,
    json_body,
    req_bool,
    req_enum,
    req_string,
)

bp = Blueprint("devices", __name__)

LIVE_ASSIGNMENT_STATES = ("ACTIVE", "SILENT", "SUSPENDED")


@bp.post("/eas-devices")
@guard("StationEngineer")
def create_device():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    model_code = req_string(body, "model_code")
    device_role = req_enum(body, "device_role", DEVICE_ROLES)
    firmware_version = req_string(body, "firmware_version")

    station = get_station(station_id)
    check_station_ownership(station)

    device = base_row()
    device.update({
        "station_id": station_id,
        "model_code": model_code,
        "device_role": device_role,
        "firmware_version": firmware_version,
        "status": "REGISTERED",
        "readiness_check_passed": False,
        "last_readiness_check_at": None,
    })
    db.devices[device["id"]] = device
    mark_created(device)
    return object_response(serializers.device(device), 201)


@bp.get("/eas-devices/<device_id>")
@guard(*ANY_ROLE)
def read_device(device_id):
    device = get_device(device_id)
    return object_response(serializers.device(device))


@bp.get("/eas-devices")
@guard(*ANY_ROLE)
def list_devices():
    rows = list(db.devices.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("status", "status"),
        ("device_role", "device_role"),
    ))
    return collection_response(rows, request, serializers.device)


@bp.post("/eas-devices/<device_id>/readiness-check")
@guard("StationEngineer")
def readiness_check(device_id):
    body = json_body(request)
    self_test_passed = req_bool(body, "self_test_passed")
    firmware_current = req_bool(body, "firmware_current")

    device = get_device(device_id)
    station = db.stations.get(device["station_id"])
    if station is not None:
        check_station_ownership(station)

    if device["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_DEVICE_DECOMMISSIONED")

    passed = bool(self_test_passed and firmware_current)
    device["readiness_check_passed"] = passed
    device["last_readiness_check_at"] = clock.now()
    if passed and device["status"] == "REGISTERED":
        device["status"] = "READY"
    touch(device)
    return object_response(serializers.device(device))


@bp.post("/eas-devices/<device_id>/decommission")
@guard("ComplianceAdmin")
def decommission_device(device_id):
    device = get_device(device_id)

    # rung 7 — state
    if device["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_DEVICE_DECOMMISSIONED")

    # rung 11 — no live assignment may reference the unit
    for a in store.assignments_of_device(device["id"]):
        if a["status"] in LIVE_ASSIGNMENT_STATES:
            raise ApiError("ERR_DEVICE_HAS_LIVE_ASSIGNMENTS")

    device["status"] = "DECOMMISSIONED"
    touch(device)
    return object_response(serializers.device(device))
