"""ScreeningLane endpoints (PRD 3.7)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, plain_action
from db import db, make_record, touch
from errors import ApiError
from response import object_response
from routes._common import get_event, get_lane, match_filters, paginated

bp = Blueprint("lanes", __name__)

LANE_TYPES = ("WALKTHROUGH_MAG", "HANDHELD_WAND", "BAG_CHECK", "EXPRESS_NO_BAG")
LANE_STATUSES = ("PLANNED", "OPEN", "HOLD", "CLOSED")
LANE_ACTIONS = ("OPEN", "HOLD", "CLOSE")
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "IncidentCommander", "PostSupervisor"}


@bp.post("/security-events/<event_id>/screening-lanes")
def create_lane(event_id):
    authenticate({"StaffingCoordinator"})
    payload = valid.body()
    zone_id = valid.req_string(payload, "zone_id")
    lane_type = valid.req_enum(payload, "lane_type", LANE_TYPES)
    nominal_throughput_pph = valid.req_int(payload, "nominal_throughput_pph", minimum=1)
    operator_capacity = valid.req_int(payload, "operator_capacity", minimum=1)
    open_from = valid.req_datetime(payload, "open_from")
    open_to = valid.req_datetime(payload, "open_to")
    if open_to[1] <= open_from[1]:
        valid.bad("Field 'open_to' must be strictly after 'open_from'.")

    event = get_event(event_id)
    zone = db.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    if zone.get("venue_id") != event.get("venue_id"):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH", "The referenced zone does not belong to the event's venue."
        )

    record = make_record(
        {
            "event_id": event["id"],
            "zone_id": zone["id"],
            "lane_type": lane_type,
            "nominal_throughput_pph": nominal_throughput_pph,
            "operator_capacity": operator_capacity,
            "open_from": open_from[0],
            "open_to": open_to[0],
            "status": "PLANNED",
            "assigned_operator_count": 0,
            "effective_throughput_pph": 0,
        }
    )
    db.lanes[record["id"]] = record
    return object_response(serial.lane(record), 201)


@bp.get("/screening-lanes/<lane_id>")
def read_lane(lane_id):
    authenticate(READ_ROLES)
    lane = get_lane(lane_id)
    return object_response(serial.lane(lane))


@bp.get("/screening-lanes")
def list_lanes():
    authenticate(READ_ROLES)
    filters = {
        "event_id": valid.query_string("event_id"),
        "zone_id": valid.query_string("zone_id"),
        "status": valid.query_enum("status", LANE_STATUSES),
        "lane_type": valid.query_enum("lane_type", LANE_TYPES),
    }
    records = [l for l in db.lanes.values() if match_filters(l, filters)]
    return paginated(records, serial.lane)


@bp.post("/screening-lanes/<lane_id>/status")
def lane_status(lane_id):
    authenticate({"StaffingCoordinator", "SecurityDirector"})
    payload = valid.body()
    action = plain_action(payload, LANE_ACTIONS)

    lane = get_lane(lane_id)
    event = db.events.get(lane.get("event_id"))
    status = lane.get("status")

    if action == "OPEN":
        if status not in ("PLANNED", "HOLD"):
            raise ApiError("ERR_INVALID_STATE", "This lane may not be opened from '%s'." % status)
        if status == "PLANNED":
            if event is None or event.get("status") not in ("BRIEFED", "DOORS_OPEN", "IN_PROGRESS"):
                raise ApiError("ERR_INVALID_STATE", "The event is not open for lane operations.")
        else:
            if event is not None and engine.open_critical_incident_count(event["id"]) != 0:
                raise ApiError(
                    "ERR_INVALID_STATE", "An open critical incident blocks lane reopening."
                )
        if event is not None and event.get("gate_posture") == "FROZEN":
            raise ApiError("ERR_EVENT_GATE_FROZEN")
        if engine.lane_operator_count(lane["id"]) < 1:
            raise ApiError("ERR_LANE_UNSTAFFED")
        lane["status"] = "OPEN"

    elif action == "HOLD":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Only an OPEN lane may be held.")
        lane["status"] = "HOLD"

    else:  # CLOSE
        if status not in ("PLANNED", "OPEN", "HOLD"):
            raise ApiError("ERR_INVALID_STATE", "This lane is already closed.")
        lane["status"] = "CLOSED"

    engine.recompute_lane(lane)
    touch(lane)
    return object_response(serial.lane(lane))
