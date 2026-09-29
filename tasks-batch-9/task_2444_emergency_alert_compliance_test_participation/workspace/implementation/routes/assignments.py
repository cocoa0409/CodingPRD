"""MonitoringAssignment endpoints (PRD 3.3)."""

from flask import Blueprint, request

import clock
import serializers
import store
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import scoring
from store import base_row, db, mark_created, touch
from validators import (
    SOURCE_TYPES,
    get_assignment,
    get_device,
    get_station,
    json_body,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("assignments", __name__)


@bp.post("/monitoring-assignments")
@guard("StationEngineer")
def create_assignment():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    device_id = req_string(body, "device_id")
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    source_call_sign = req_string(body, "source_call_sign")
    expected_station_version = req_int(body, "expected_station_version")

    # rung 4 — body ids resolve in declared order: station_id then device_id
    station = get_station(station_id)
    device = get_device(device_id)

    # rung 5 — ownership
    check_station_ownership(station)

    # rung 6 — optimistic concurrency
    if expected_station_version != station["version"]:
        raise ApiError("ERR_STALE_STATION_VERSION")

    # rung 7 — state
    if device["status"] != "READY":
        raise ApiError("ERR_DEVICE_NOT_READY")

    # rung 9 — cross-row referential coherence
    if device["station_id"] != station_id:
        raise ApiError("ERR_DEVICE_STATION_MISMATCH")

    assignment = base_row()
    assignment.update({
        "station_id": station_id,
        "device_id": device_id,
        "source_type": source_type,
        "source_call_sign": source_call_sign,
        "status": "ACTIVE",
        "last_receipt_at": None,
        "silence_flagged_at": None,
        "superseded_assignment_id": None,
    })
    db.assignments[assignment["id"]] = assignment
    mark_created(assignment)

    # supersede the prior ACTIVE row covering the same source type
    superseded_id = None
    for other in store.assignments_of_station(station_id):
        if other["id"] == assignment["id"]:
            continue
        if other["status"] == "ACTIVE" and other["source_type"] == source_type:
            other["status"] = "DECOMMISSIONED"
            touch(other)
            superseded_id = other["id"]
    assignment["superseded_assignment_id"] = superseded_id

    # accessible_source_count is recomputed AFTER the supersede has landed,
    # then the station recompute event fires (which also bumps the version).
    scoring.recompute_station(station)
    return object_response(serializers.assignment(assignment), 201)


@bp.get("/monitoring-assignments/<assignment_id>")
@guard(*ANY_ROLE)
def read_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    return object_response(serializers.assignment(assignment))


@bp.get("/monitoring-assignments")
@guard(*ANY_ROLE)
def list_assignments():
    rows = list(db.assignments.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("device_id", "device_id"),
        ("source_type", "source_type"),
        ("status", "status"),
        ("superseded_assignment_id", "superseded_assignment_id"),
    ))
    return collection_response(rows, request, serializers.assignment)


@bp.post("/monitoring-assignments/<assignment_id>/record-receipt")
@guard("StationEngineer")
def record_receipt(assignment_id):
    assignment = get_assignment(assignment_id)
    station = db.stations.get(assignment["station_id"])
    if station is not None:
        check_station_ownership(station)

    if assignment["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")

    assignment["last_receipt_at"] = clock.now()
    if assignment["status"] == "SILENT":
        assignment["status"] = "ACTIVE"
        assignment["silence_flagged_at"] = None
    touch(assignment)

    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.assignment(assignment))


@bp.post("/monitoring-assignments/<assignment_id>/decommission")
@guard("StationEngineer")
def decommission_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    station = db.stations.get(assignment["station_id"])
    if station is not None:
        check_station_ownership(station)

    if assignment["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")

    assignment["status"] = "DECOMMISSIONED"
    touch(assignment)

    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.assignment(assignment))


@bp.post("/monitoring-assignments/<assignment_id>/reinstate")
@guard("StationEngineer")
def reinstate_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    station = db.stations.get(assignment["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 7 — state family first
    if assignment["status"] != "DECOMMISSIONED":
        raise ApiError("ERR_ASSIGNMENT_NOT_DECOMMISSIONED")
    device = db.devices.get(assignment["device_id"])
    if device is None or device["status"] != "READY":
        raise ApiError("ERR_DEVICE_NOT_READY")

    # rung 11 — no other ACTIVE assignment may already cover the source type
    for other in store.assignments_of_station(assignment["station_id"]):
        if other["id"] == assignment["id"]:
            continue
        if other["status"] == "ACTIVE" and other["source_type"] == assignment["source_type"]:
            raise ApiError("ERR_SOURCE_TYPE_ALREADY_COVERED")

    assignment["status"] = "ACTIVE"
    touch(assignment)

    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.assignment(assignment))
