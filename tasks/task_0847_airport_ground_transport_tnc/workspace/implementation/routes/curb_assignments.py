from flask import Blueprint, request

import serializers
from common import (
    authenticate, require_role, body_json, as_str, parse_dt,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record

bp = Blueprint("curb_assignments", __name__)


@bp.route("/v1/curb-assignments", methods=["POST"])
def create_curb_assignment():
    _uid, role = authenticate()
    require_role(role, {"CurbCoordinator"})
    body = body_json()
    curb_zone_id = as_str(body, "curb_zone_id")
    trip_id = as_str(body, "trip_id")
    start_ts = parse_dt(body, "start_ts")
    end_ts = parse_dt(body, "end_ts")

    # existence, left-to-right: curb_zone_id then trip_id
    zone = must_exist(db.curb_zones, curb_zone_id)
    trip = must_exist(db.trips, trip_id)

    if trip["status"] not in ("DISPATCHED", "PICKED_UP"):
        raise ApiError("ERR_TRIP_NOT_ACTIVE", 409, "Trip is not operationally live")

    # half-open [start,end) overlap count of ACTIVE assignments on this zone
    overlap = 0
    for a in db.curb_assignments.values():
        if a["curb_zone_id"] != curb_zone_id or a["status"] != "ACTIVE":
            continue
        if a["start_ts"] < end_ts and start_ts < a["end_ts"]:
            overlap += 1
    if overlap >= zone["capacity"]:
        raise ApiError("ERR_CURB_CONFLICT", 409, "Curb zone at capacity for requested window")

    rec = base_record()
    rec.update({
        "curb_zone_id": curb_zone_id,
        "trip_id": trip_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "status": "ACTIVE",
    })
    db.curb_assignments[rec["id"]] = rec
    return respond(serializers.curb_assignment(rec), "object", 201)


@bp.route("/v1/curb-assignments/<curb_assignment_id>", methods=["GET"])
def get_curb_assignment(curb_assignment_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    a = must_exist(db.curb_assignments, curb_assignment_id)
    return respond(serializers.curb_assignment(a), "object", 200)


@bp.route("/v1/curb-assignments", methods=["GET"])
def list_curb_assignments():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    curb_zone_id = request.args.get("curb_zone_id")
    trip_id = request.args.get("trip_id")
    status = request.args.get("status")
    items = [
        a for a in db.curb_assignments.values()
        if (curb_zone_id is None or a["curb_zone_id"] == curb_zone_id)
        and (trip_id is None or a["trip_id"] == trip_id)
        and (status is None or a["status"] == status)
    ]
    return list_response(items, serializers.curb_assignment, limit, offset)
