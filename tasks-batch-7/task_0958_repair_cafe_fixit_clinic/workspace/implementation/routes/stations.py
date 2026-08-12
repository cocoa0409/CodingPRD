"""Station CRUD and lifecycle."""

from flask import Blueprint

import db
import serializers as ser
import services
from errors import (
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_EVENT_STATE,
    ERR_INVALID_STATION_STATE,
    ERR_ITEMS_IN_FLIGHT,
    ERR_NO_QUALIFIED_FIXER_CHECKED_IN,
    ERR_STATION_HAS_CHECKED_IN_FIXERS,
    ERR_STATION_NOT_FOUND,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_enum, as_int, as_str, body, list_response, req

bp = Blueprint("stations", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
STATION_CATEGORIES = ("ELECTRONICS", "TEXTILE", "BIKE")


def get_station_or_404(station_id):
    station = db.stations.get(station_id)
    if station is None:
        raise_err(ERR_STATION_NOT_FOUND, "Station %s does not exist" % station_id)
    return station


def _has_qualified_fixer_checked_in(station):
    """A CHECKED_IN shift at the station whose fixer holds a matching-category skill."""
    for s in db.shifts.values():
        if s["station_id"] != station["id"] or s["status"] != "CHECKED_IN":
            continue
        for sk in db.skills.values():
            if sk["fixer_id"] == s["fixer_id"] and sk["category"] == station["category"]:
                return True
    return False


@bp.post("/api/stations")
@require_roles("Coordinator")
def create_station():
    b = body()
    event_id = as_str(req(b, "event_id"), "event_id")
    if event_id not in db.events:
        raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    category = as_enum(req(b, "category"), "category", STATION_CATEGORIES)
    label = as_str(req(b, "label"), "label")
    capacity = as_int(req(b, "capacity"), "capacity", lo=1)
    rec = db.stamp_new(
        {
            "event_id": event_id,
            "category": category,
            "label": label,
            "capacity": capacity,
            "status": "SETUP",
        }
    )
    db.stations[rec["id"]] = rec
    return success(ser.station(rec), 201)


@bp.get("/api/stations")
@require_roles(*ALL_ROLES)
def list_stations():
    return list_response(
        db.stations.values(),
        ser.station,
        [("event_id", "event_id"), ("status", "status"), ("category", "category")],
    )


@bp.get("/api/stations/<station_id>")
@require_roles(*ALL_ROLES)
def get_station(station_id):
    return success(ser.station(get_station_or_404(station_id)), 200)


@bp.post("/api/stations/<station_id>/open")
@require_roles("Coordinator")
def open_station(station_id):
    station = get_station_or_404(station_id)
    if station["status"] != "SETUP":
        raise_err(ERR_INVALID_STATION_STATE, "Only a SETUP station can be opened")
    event = db.events[station["event_id"]]
    if event["status"] not in ("PUBLISHED", "INTAKE_OPEN", "REPAIR_ACTIVE"):
        raise_err(ERR_INVALID_EVENT_STATE, "Event phase does not permit opening stations")
    if not _has_qualified_fixer_checked_in(station):
        raise_err(
            ERR_NO_QUALIFIED_FIXER_CHECKED_IN,
            "No checked-in fixer holds a skill matching the station category",
        )
    station["status"] = "OPEN"
    db.touch(station)
    return success(ser.station(station), 200)


@bp.post("/api/stations/<station_id>/pause")
@require_roles("Coordinator")
def pause_station(station_id):
    station = get_station_or_404(station_id)
    if station["status"] != "OPEN":
        raise_err(ERR_INVALID_STATION_STATE, "Only an OPEN station can be paused")
    for it in db.items.values():
        if it["assigned_station_id"] == station["id"] and it["status"] == "IN_REPAIR":
            raise_err(ERR_ITEMS_IN_FLIGHT, "An item is in repair at this station")
    station["status"] = "PAUSED"
    db.touch(station)
    return success(ser.station(station), 200)


@bp.post("/api/stations/<station_id>/resume")
@require_roles("Coordinator")
def resume_station(station_id):
    station = get_station_or_404(station_id)
    if station["status"] != "PAUSED":
        raise_err(ERR_INVALID_STATION_STATE, "Only a PAUSED station can be resumed")
    if not _has_qualified_fixer_checked_in(station):
        raise_err(
            ERR_NO_QUALIFIED_FIXER_CHECKED_IN,
            "No checked-in fixer holds a skill matching the station category",
        )
    station["status"] = "OPEN"
    db.touch(station)
    return success(ser.station(station), 200)


@bp.post("/api/stations/<station_id>/close")
@require_roles("Coordinator")
def close_station(station_id):
    station = get_station_or_404(station_id)
    if station["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATION_STATE, "Station is already closed")
    if station["status"] == "OPEN" and services.checked_in_count(station["id"]) > 0:
        raise_err(ERR_STATION_HAS_CHECKED_IN_FIXERS, "Fixers are still checked in")
    station["status"] = "CLOSED"
    db.touch(station)
    return success(ser.station(station), 200)
