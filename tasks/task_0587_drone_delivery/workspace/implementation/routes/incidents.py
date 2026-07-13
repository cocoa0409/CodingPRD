"""Incidents, the review fork, and maintenance work orders (PRD 3.8, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import serializers
import validation as v
from auth import require
from db import db, get_or_404, new_record, touch
from errors import err
from response import ok
from routes import filtered, list_response
from services import flight_service

bp = Blueprint("incidents", __name__)

STAFF = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "MaintenanceTech")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
CATEGORIES = ("HARD_LANDING", "LOST_LINK", "PAYLOAD_RELEASE", "AIRSPACE_DEVIATION", "GROUND_DAMAGE")
INCIDENT_STATUSES = ("OPEN", "UNDER_REVIEW", "MAINTENANCE_REQUIRED", "CLOSED")
WORK_TYPES = ("INSPECTION", "REPAIR", "BATTERY_SWAP", "OVERHAUL")
LOG_STATUSES = ("SCHEDULED", "COMPLETED")


# --- incidents ------------------------------------------------------------


@bp.post("/incidents")
@require("DispatchOperator", "MaintenanceTech", "FlightDirector")
def create_incident():
    body = v.body()
    drone_id = v.as_string(body, "drone_id")
    severity = v.as_enum(body, "severity", SEVERITIES)
    category = v.as_enum(body, "category", CATEGORIES)
    narrative = v.as_string(body, "narrative")
    flight_id = v.as_string(body, "flight_id", required=False, default=None)

    get_or_404("Drone", drone_id)
    if flight_id is not None:
        get_or_404("Flight", flight_id)

    rec = new_record(
        "Incident",
        {
            "drone_id": drone_id,
            "flight_id": flight_id,
            "severity": severity,
            "category": category,
            "narrative": narrative,
            "status": "OPEN",
        },
    )
    return ok(serializers.incident(rec), 201)


@bp.get("/incidents")
@require(*STAFF)
def list_incidents():
    limit, offset = v.pagination()
    rows = filtered(
        db.incidents.values(),
        drone_id=v.query_str("drone_id"),
        flight_id=v.query_str("flight_id"),
        status=v.query_enum("status", INCIDENT_STATUSES),
    )
    return list_response(rows, serializers.incident, limit, offset)


@bp.get("/incidents/<incident_id>")
@require(*STAFF)
def read_incident(incident_id):
    return ok(serializers.incident(get_or_404("Incident", incident_id)))


@bp.post("/incidents/<incident_id>/review")
@require("MaintenanceTech")
def review_incident(incident_id):
    incident = get_or_404("Incident", incident_id)
    if incident["status"] != "OPEN":
        raise err("ERR_INCIDENT_NOT_OPEN")
    incident["status"] = "UNDER_REVIEW"
    touch(incident)
    return ok(serializers.incident(incident))


@bp.post("/incidents/<incident_id>/outcome")
@require("MaintenanceTech")
def incident_outcome(incident_id):
    body = v.body()
    outcome = v.as_enum(body, "outcome", ("NO_ACTION", "MAINTENANCE_REQUIRED"))

    incident = get_or_404("Incident", incident_id)
    if incident["status"] != "UNDER_REVIEW":
        raise err("ERR_INCIDENT_NOT_UNDER_REVIEW")

    if outcome == "NO_ACTION":
        # Branch A: the severity points migrate into the advisory bucket. Nothing else moves.
        incident["status"] = "CLOSED"
        touch(incident)
        return ok(serializers.incident(incident))

    # Branch B: the grounding cascade.
    incident["status"] = "MAINTENANCE_REQUIRED"
    touch(incident)

    drone = db.drones[incident["drone_id"]]
    flight_service.ground_drone_cascade(drone)
    flight_service.schedule_maintenance(drone["id"], "REPAIR", 120, incident_id=incident["id"])

    return ok(serializers.incident(incident))


# --- maintenance logs -----------------------------------------------------


@bp.post("/maintenance-logs")
@require("MaintenanceTech")
def create_maintenance_log():
    body = v.body()
    drone_id = v.as_string(body, "drone_id")
    work_type = v.as_enum(body, "work_type", WORK_TYPES)
    scheduled_start = v.as_datetime(body, "scheduled_start")
    scheduled_end = v.as_datetime(body, "scheduled_end")
    expected_version = v.as_integer(body, "expected_drone_version")
    notes = v.as_string(body, "notes", required=False, default="")

    drone = get_or_404("Drone", drone_id)

    if expected_version != drone["version"]:
        raise err("ERR_STALE_DRONE_VERSION")

    # Half-open, zero-buffer, capacity-1 overlap (PRD 3.9).
    for log in db.maintenance_logs.values():
        if log["drone_id"] != drone_id or log["status"] != "SCHEDULED":
            continue
        if scheduled_start < log["scheduled_end"] and log["scheduled_start"] < scheduled_end:
            raise err("ERR_MAINTENANCE_WINDOW_CONFLICT")

    rec = new_record(
        "MaintenanceLog",
        {
            "drone_id": drone_id,
            "incident_id": None,
            "work_type": work_type,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
            "completed_at": None,
            "notes": notes,
        },
    )
    touch(drone)
    return ok(serializers.maintenance_log(rec), 201)


@bp.get("/maintenance-logs")
@require(*STAFF)
def list_maintenance_logs():
    limit, offset = v.pagination()
    rows = filtered(
        db.maintenance_logs.values(),
        drone_id=v.query_str("drone_id"),
        incident_id=v.query_str("incident_id"),
        status=v.query_enum("status", LOG_STATUSES),
    )
    return list_response(rows, serializers.maintenance_log, limit, offset)


@bp.get("/maintenance-logs/<log_id>")
@require(*STAFF)
def read_maintenance_log(log_id):
    return ok(serializers.maintenance_log(get_or_404("MaintenanceLog", log_id)))


@bp.post("/maintenance-logs/<log_id>/complete")
@require("MaintenanceTech")
def complete_maintenance_log(log_id):
    log = get_or_404("MaintenanceLog", log_id)
    if log["status"] != "SCHEDULED":
        raise err("ERR_MAINTENANCE_NOT_SCHEDULED")

    drone = db.drones[log["drone_id"]]
    battery_id = drone.get("installed_battery_id")
    battery = db.batteries.get(battery_id) if battery_id else None
    if battery is None or battery["state"] != "READY":
        raise err("ERR_BATTERY_NOT_READY", "The airframe needs a READY pack installed.")

    log["status"] = "COMPLETED"
    log["completed_at"] = db.now()
    touch(log)

    drone["hours_since_service"] = Decimal("0")
    if drone["status"] == "GROUNDED":
        drone["status"] = "IDLE"
    touch(drone)

    if log["incident_id"]:
        incident = db.incidents.get(log["incident_id"])
        if incident is not None and incident["status"] == "MAINTENANCE_REQUIRED":
            incident["status"] = "CLOSED"
            touch(incident)

    return ok(serializers.maintenance_log(log))
