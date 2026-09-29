"""EquipmentOutage endpoints (PRD 3.4)."""

from flask import Blueprint, request

import clock
import serializers
import store
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_bool, filter_equals
from services import calculations as calc
from services import scoring
from store import base_row, db, mark_created, touch
from validators import (
    get_device,
    get_outage,
    json_body,
    opt_string,
    req_datetime,
    req_string,
)

bp = Blueprint("outages", __name__)

BLOCKING_OUTAGE_STATES = ("OPEN", "REPAIR_IN_PROGRESS", "VERIFICATION_FAILED")


@bp.post("/equipment-outages")
@guard("StationEngineer")
def create_outage():
    body = json_body(request)
    device_id = req_string(body, "device_id")
    detected_at = req_datetime(body, "detected_at")
    failure_summary = req_string(body, "failure_summary")

    device = get_device(device_id)
    station = db.stations.get(device["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 7 — state
    if device["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_DEVICE_DECOMMISSIONED")

    # rung 10 — clock-relative window
    if detected_at > clock.now():
        raise ApiError("ERR_OUTAGE_DETECTED_IN_FUTURE")

    outage = base_row()
    outage.update({
        "device_id": device_id,
        "detected_at": detected_at,
        "failure_summary": failure_summary,
        "notified_at": clock.now(),
        "repair_started_at": None,
        "restored_at": None,
        "status": "OPEN",
        "repair_cycle_count": 0,
        "continuous_downtime_hours": None,
        "obligation_downtime_hours": None,
        "continuous_clock_breached": False,
        "obligation_breached": False,
    })
    db.outages[outage["id"]] = outage
    mark_created(outage)

    # the four-hop outage cascade (PRD 2.11)
    scoring.outage_cascade(device)
    return object_response(serializers.outage(outage), 201)


@bp.get("/equipment-outages/<outage_id>")
@guard(*ANY_ROLE)
def read_outage(outage_id):
    outage = get_outage(outage_id)
    return object_response(serializers.outage(outage))


@bp.get("/equipment-outages")
@guard(*ANY_ROLE)
def list_outages():
    rows = list(db.outages.values())
    rows = filter_equals(rows, request, (
        ("device_id", "device_id"),
        ("status", "status"),
    ))
    rows = filter_bool(rows, request, "obligation_breached", "obligation_breached")
    return collection_response(rows, request, serializers.outage)


@bp.post("/equipment-outages/<outage_id>/start-repair")
@guard("StationEngineer")
def start_repair(outage_id):
    outage = get_outage(outage_id)
    station = _station_of(outage)
    if station is not None:
        check_station_ownership(station)

    if outage["status"] not in ("OPEN", "VERIFICATION_FAILED"):
        raise ApiError("ERR_OUTAGE_NOT_REPAIRABLE")

    if outage["status"] == "VERIFICATION_FAILED":
        outage["repair_cycle_count"] += 1
    outage["status"] = "REPAIR_IN_PROGRESS"
    outage["repair_started_at"] = clock.now()
    touch(outage)
    return object_response(serializers.outage(outage))


@bp.post("/equipment-outages/<outage_id>/restore")
@guard("StationEngineer")
def restore_outage(outage_id):
    outage = get_outage(outage_id)
    station = _station_of(outage)
    if station is not None:
        check_station_ownership(station)

    if outage["status"] != "REPAIR_IN_PROGRESS":
        raise ApiError("ERR_OUTAGE_NOT_IN_REPAIR")

    restored_at = clock.now()
    outage["status"] = "RESTORED"
    outage["restored_at"] = restored_at
    figures = calc.outage_downtime_hours(outage["detected_at"], restored_at)
    outage.update(figures)
    touch(outage)
    return object_response(serializers.outage(outage))


@bp.post("/equipment-outages/<outage_id>/fail-verification")
@guard("ComplianceAdmin")
def fail_verification(outage_id):
    body = json_body(request)
    opt_string(body, "verification_note", allow_empty=True)

    outage = get_outage(outage_id)
    if outage["status"] != "RESTORED":
        raise ApiError("ERR_OUTAGE_NOT_RESTORED")

    outage["status"] = "VERIFICATION_FAILED"
    outage["restored_at"] = None
    outage["continuous_downtime_hours"] = None
    outage["obligation_downtime_hours"] = None
    touch(outage)
    return object_response(serializers.outage(outage))


@bp.post("/equipment-outages/<outage_id>/close")
@guard("ComplianceAdmin")
def close_outage(outage_id):
    outage = get_outage(outage_id)
    if outage["status"] != "RESTORED":
        raise ApiError("ERR_OUTAGE_NOT_RESTORED")

    outage["status"] = "CLOSED"
    touch(outage)

    device = db.devices.get(outage["device_id"])
    now = clock.now()
    if device is not None:
        blocked = False
        for other in store.outages_of_device(device["id"]):
            if other["id"] == outage["id"]:
                continue
            if other["status"] in BLOCKING_OUTAGE_STATES:
                blocked = True
                break
        if not blocked and device["status"] == "FAILED":
            device["status"] = "READY"
            touch(device)
            for a in store.assignments_of_device(device["id"]):
                if a["status"] == "SUSPENDED":
                    a["status"] = "SILENT"
                    a["silence_flagged_at"] = now
                    touch(a)

        station = db.stations.get(device["station_id"])
        if station is not None:
            scoring.recompute_station(station)

    return object_response(serializers.outage(outage))


def _station_of(outage):
    device = db.devices.get(outage["device_id"])
    if device is None:
        return None
    return db.stations.get(device["station_id"])
