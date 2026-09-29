"""Safety events and posture recovery."""
from flask import Blueprint

import derive
import serializers as ser
from auth import actor, require_station_owner
from constants import DETECTED_BY, SAFETY_KINDS, SAFETY_STATUSES, SEVERITIES
from envelope import created, listing, ok
from errors import raise_error
from helpers import (
    apply_freeze_cascade,
    apply_subsystem_clear,
    apply_subsystem_open,
    get_event,
    get_station,
)
from store import base_row, db, touch
from validate import (
    bad,
    f_enum,
    f_int,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
)

bp = Blueprint("safety", __name__)


@bp.get("/safety-events/<event_id>")
def read_event(event_id):
    actor("PlatformAdmin", "SafetyOfficer", "StationOperator", "ComplianceAdmin")
    return ok(ser.safety_event(get_event(event_id)))


@bp.get("/stations/<station_id>/safety-events")
def list_events(station_id):
    actor("PlatformAdmin", "StationOperator", "SafetyOfficer", "ComplianceAdmin")
    station = get_station(station_id)
    limit, offset = pagination()
    status = q_enum("status", SAFETY_STATUSES)
    severity = q_enum("severity", SEVERITIES)
    rows = derive.events_of(station["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    page = paginate(rows, limit, offset)
    return listing([ser.safety_event(r) for r in page], limit, offset, len(rows))


@bp.post("/safety-events")
def open_event():
    user_id, role = actor("SafetyOfficer", "StationOperator")
    body = json_body()
    raw_station = body.get("station_id")
    if isinstance(raw_station, str) and raw_station.strip():
        require_station_owner(role, user_id, raw_station)

    station_id = f_str(body, "station_id")
    kind = f_enum(body, "kind", SAFETY_KINDS)
    severity = f_enum(body, "severity", SEVERITIES)
    affected_nozzle_count = f_int(body, "affected_nozzle_count", ge=0)
    detected_by = f_enum(body, "detected_by", DETECTED_BY)

    station = get_station(station_id)
    if affected_nozzle_count > station["nozzle_count"]:
        bad("Field 'affected_nozzle_count' must not exceed the station's nozzle_count.")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "kind": kind,
        "severity": severity,
        "affected_nozzle_count": affected_nozzle_count,
        "detected_by": detected_by,
        "opened_by_user_id": user_id,
        "cleared_by_user_id": None,
        "opened_at": db.clock,
        "acknowledged_at": None,
        "cleared_at": None,
        "status": "OPEN",
        "corrective_action": None,
    })
    db.safety_events[row["id"]] = row

    apply_subsystem_open(station, kind)
    apply_freeze_cascade(station)
    touch(station)
    return created(ser.safety_event(row))


@bp.post("/safety-events/<event_id>/acknowledge")
def acknowledge_event(event_id):
    actor("SafetyOfficer")
    event = get_event(event_id)
    if event["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    event["acknowledged_at"] = db.clock
    event["status"] = "ACKNOWLEDGED"
    touch(event)
    return ok(ser.safety_event(event))


@bp.post("/safety-events/<event_id>/clear")
def clear_event(event_id):
    user_id, _role = actor("SafetyOfficer")
    event = get_event(event_id)
    body = json_body()
    corrective_action = f_str(body, "corrective_action")

    if event["status"] != "ACKNOWLEDGED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if user_id == event["opened_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES")

    event["cleared_at"] = db.clock
    event["cleared_by_user_id"] = user_id
    event["corrective_action"] = corrective_action
    event["status"] = "CLEARED"
    touch(event)

    station = db.stations[event["station_id"]]
    apply_subsystem_clear(station, event["kind"], event["id"])
    touch(station)
    return ok(ser.safety_event(event))
