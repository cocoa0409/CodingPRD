"""RoadSegment endpoints (PRD 3.1, 2.8)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_SEGMENT_NOT_FOUND
from middleware import get_caller, check_role, COORD, LEADER
from response import success_object
from routes.helpers import list_response
from services.core import stamp_new, public
from util import dec, money2
from validate import get_body, req_str, req_enum, req_number, opt_bool, require_resource

bp = Blueprint("segments", __name__)

SEGMENT_TYPES = ["ROADWAY", "RIVERBANK"]
SEGMENT_STATUSES = ["AVAILABLE", "ADOPTED"]


@bp.post("/program/segments")
def create_segment():
    caller = get_caller()
    check_role(caller, [COORD])
    body = get_body()
    route_name = req_str(body, "route_name")
    start = req_number(body, "mile_marker_start")
    end = req_number(body, "mile_marker_end")
    segment_type = req_enum(body, "segment_type", SEGMENT_TYPES)
    water_adjacent = opt_bool(body, "water_adjacent", False)
    if not dec(end) > dec(start):
        raise_error(ERR_INVALID_REQUEST, "mile_marker_end must be strictly greater than mile_marker_start")
    mile_length = money2(dec(end) - dec(start))
    rec = stamp_new({
        "route_name": route_name,
        "mile_marker_start": start,
        "mile_marker_end": end,
        "mile_length": mile_length,
        "segment_type": segment_type,
        "water_adjacent": water_adjacent,
        "status": "AVAILABLE",
    })
    db["segments"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/segments/<sid>")
def get_segment(sid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("segments", sid, ERR_SEGMENT_NOT_FOUND)
    return success_object(public(rec))


def _parse_bool_param(raw, field):
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise_error(ERR_INVALID_REQUEST, f"query parameter {field} must be true or false")


@bp.get("/program/segments")
def list_segments():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "status": request.args.get("status"),
        "water_adjacent": _parse_bool_param(request.args.get("water_adjacent"), "water_adjacent"),
    }
    return list_response("segments", caller, filters=filters)
