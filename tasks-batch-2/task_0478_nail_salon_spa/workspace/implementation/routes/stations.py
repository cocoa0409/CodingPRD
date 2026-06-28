"""Stations and the sanitation discipline (PRD §3.2)."""
from flask import Blueprint, request

from common import (json_body, make_record, get_str, get_bool,
                    parse_pagination, paginate)
from db import db
from errors import err, ERR_DUPLICATE_RESOURCE
from middleware import authorize
from lookup import get_station
from derive import station_sanitation_status
from response import success_object, success_list
from serialize import station_out, sanitation_log_out

bp = Blueprint("stations", __name__)

READ_ROLES = {"SalonManager", "FrontDesk", "Technician"}


@bp.route("/stations", methods=["POST"])
def create_station():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    name = get_str(body, "name", required=True)
    requires_autoclave = get_bool(body, "requires_autoclave", required=False, default=True)

    for s in db.stations.values():
        if s["name"] == name:
            raise err(ERR_DUPLICATE_RESOURCE, "Station name already exists")

    rec = make_record({
        "name": name,
        "requires_autoclave": requires_autoclave,
    })
    db.stations[rec["id"]] = rec
    return success_object(station_out(rec), status=201)


@bp.route("/stations", methods=["GET"])
def list_stations():
    authorize(READ_ROLES)
    items = list(db.stations.values())
    ss = request.args.get("sanitation_status")
    if ss is not None:
        items = [s for s in items if station_sanitation_status(s) == ss]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([station_out(s) for s in page], limit, offset, total)


@bp.route("/stations/<sid>", methods=["GET"])
def get_one_station(sid):
    authorize(READ_ROLES)
    rec = get_station(sid)
    return success_object(station_out(rec), status=200)


@bp.route("/stations/<sid>/sanitation-logs", methods=["GET"])
def station_sanitation_logs(sid):
    authorize(READ_ROLES)
    get_station(sid)
    items = [lg for lg in db.sanitation_logs.values() if lg["station_id"] == sid]
    cr = request.args.get("cycle_result")
    if cr is not None:
        items = [lg for lg in items if lg["cycle_result"] == cr]
    limit, offset = parse_pagination(request.args)
    # newest first (PRD §1.5 / endpoint description)
    page, total = paginate(items, limit, offset, reverse=True)
    return success_list([sanitation_log_out(lg) for lg in page], limit, offset, total)
