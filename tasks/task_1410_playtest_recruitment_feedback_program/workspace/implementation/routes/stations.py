"""Lab station endpoints."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch, check_unique, require_enum
from errors import raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from services.serializers import public

bp = make_blueprint("stations")


def _get_station(sid):
    s = db.lab_stations.get(sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "Lab station not found")
    return s


@bp.route("/playtests/lab-stations", methods=["POST"])
def create_station():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    station_code = require_string(body, "station_code")
    location = require_string(body, "location")
    equipment_tags = body.get("equipment_tags", [])
    if not isinstance(equipment_tags, list):
        raise_error(ERR_INVALID_REQUEST, "equipment_tags must be an array")
    check_unique(db.lab_stations, "station_code", station_code)
    rec = {
        "station_code": station_code,
        "location": location,
        "equipment_tags": list(equipment_tags),
        "status": "AVAILABLE",
    }
    stamp_new(rec)
    db.lab_stations[rec["id"]] = rec
    return success(public(rec, "lab_station"), status=201)


@bp.route("/playtests/lab-stations", methods=["GET"])
def list_stations():
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.lab_stations.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(s, "lab_station") for s in page], status=200, pagination=pagination)


@bp.route("/playtests/lab-stations/<sid>", methods=["GET"])
def get_station(sid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator")
    s = _get_station(sid)
    return success(public(s, "lab_station"), status=200)


@bp.route("/playtests/lab-stations/<sid>", methods=["PATCH"])
def update_station(sid):
    require_roles("ResearchOpsAdmin")
    s = _get_station(sid)
    body = get_payload()
    status = require_enum(body, "status", ("AVAILABLE", "OUT_OF_SERVICE"))
    if status == s["status"]:
        raise_error(ERR_INVALID_STATE, "Station already in status %s" % status)
    s["status"] = status
    touch(s)
    return success(public(s, "lab_station"), status=200)
