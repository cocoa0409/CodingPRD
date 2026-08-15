"""HazardReport endpoints (PRD 3.7): do-not-touch protocol, agency escalation."""
import uuid

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SEGMENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_HAZARD_NOT_FOUND,
    ERR_HAZARD_NOT_REPORTED,
    ERR_HAZARD_NOT_ACKNOWLEDGED,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from routes.helpers import list_response, hazard_owner_group_id, event_owner_group_id
from services.core import stamp_new, touch, public
from util import CLOCK
from validate import (
    get_body, req_str, req_enum, ref_id, require_resource, maybe_resource,
)

bp = Blueprint("hazards", __name__)

HAZARD_TYPES = ["CHEMICAL_CONTAINER", "SYRINGES", "PROPANE_TANK", "ASBESTOS", "OTHER"]


@bp.post("/program/hazards")
def create_hazard():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    body = get_body()
    # family 3: references that are present must resolve
    segment_id = ref_id(body, "segment_id")
    segment = maybe_resource("segments", segment_id, ERR_SEGMENT_NOT_FOUND)
    event_id = ref_id(body, "event_id")
    event = maybe_resource("events", event_id, ERR_EVENT_NOT_FOUND)
    # family 4: ownership through the referenced event's agreement, when given
    if event is not None:
        check_ownership(caller, event_owner_group_id(event))
    # family 5: shape
    if segment_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: segment_id")
    hazard_type = req_enum(body, "hazard_type", HAZARD_TYPES)
    description = req_str(body, "description")
    location_note = req_str(body, "location_note")
    rec = stamp_new({
        "segment_id": segment_id,
        "event_id": event_id,
        "hazard_type": hazard_type,
        "description": description,
        "location_note": location_note,
        "status": "REPORTED",
        "agency_reference": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "resolution_note": None,
    })
    db["hazards"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/hazards/<hid>")
def get_hazard(hid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("hazards", hid, ERR_HAZARD_NOT_FOUND)
    check_ownership(caller, hazard_owner_group_id(rec))
    return success_object(public(rec))


@bp.get("/program/hazards")
def list_hazards():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "segment_id": request.args.get("segment_id"),
        "event_id": request.args.get("event_id"),
        "status": request.args.get("status"),
    }
    # Hazards filed without an event have no owning group; listings stay unscoped.
    return list_response("hazards", caller, filters=filters)


@bp.post("/program/hazards/<hid>/acknowledge")
def acknowledge_hazard(hid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("hazards", hid, ERR_HAZARD_NOT_FOUND)
    get_body()
    if rec["status"] != "REPORTED":
        raise_error(ERR_HAZARD_NOT_REPORTED, "hazard is not REPORTED")
    rec["status"] = "ACKNOWLEDGED"
    # mint the agency notification reference and stamp the logical clock
    rec["agency_reference"] = "AGY-" + uuid.uuid4().hex[:12].upper()
    rec["acknowledged_at"] = CLOCK.now_iso()
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/hazards/<hid>/resolve")
def resolve_hazard(hid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("hazards", hid, ERR_HAZARD_NOT_FOUND)
    body = get_body()
    resolution_note = req_str(body, "resolution_note")
    if rec["status"] != "ACKNOWLEDGED":
        raise_error(ERR_HAZARD_NOT_ACKNOWLEDGED, "hazard is not ACKNOWLEDGED")
    rec["status"] = "RESOLVED"
    rec["resolution_note"] = resolution_note
    rec["resolved_at"] = CLOCK.now_iso()
    touch(rec)
    return success_object(public(rec))
