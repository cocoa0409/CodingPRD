"""Append-only sanitation logs (PRD §3.2)."""
from flask import Blueprint, request

from common import (json_body, make_record, get_str, get_enum, get_number,
                    get_int, parse_pagination, paginate)
from db import db
from errors import err, ERR_STERILIZATION_INVALID
from middleware import authorize
from lookup import get_station, get_technician, get_sanitation_log
from response import success_object, success_list
from serialize import sanitation_log_out

bp = Blueprint("sanitation_logs", __name__)

READ_ROLES = {"SalonManager", "FrontDesk", "Technician"}


@bp.route("/sanitation-logs", methods=["POST"])
def create_sanitation_log():
    authorize({"Technician", "SalonManager"})
    body = json_body(optional=False)
    station_id = get_str(body, "station_id", required=True)
    logged_by_technician_id = get_str(body, "logged_by_technician_id", required=True)
    cycle_result = get_enum(body, "cycle_result", ["PASS", "FAIL"], required=True)
    cycle_temp_c = get_number(body, "cycle_temp_c", required=True, gt=0)
    hold_minutes = get_int(body, "hold_minutes", required=True, minimum=0)

    # FK existence in body order (PRD §2.6): station_id then logged_by_technician_id
    get_station(station_id)
    get_technician(logged_by_technician_id)

    # PASS thresholds (PRD §3.2): cycle_temp_c >= 121.0 AND hold_minutes >= 30
    if cycle_result == "PASS":
        if cycle_temp_c < 121.0 or hold_minutes < 30:
            raise err(ERR_STERILIZATION_INVALID, "PASS claim is physically inconsistent")

    rec = make_record({
        "station_id": station_id,
        "logged_by_technician_id": logged_by_technician_id,
        "cycle_result": cycle_result,
        "cycle_temp_c": cycle_temp_c,
        "hold_minutes": hold_minutes,
    }, with_common=False)  # append-only: id + created_at only (PRD §2.4)
    db.sanitation_logs[rec["id"]] = rec
    # sanitation_status is derived on read from log history; no stored flag to flip.
    return success_object(sanitation_log_out(rec), status=201)


@bp.route("/sanitation-logs", methods=["GET"])
def list_sanitation_logs():
    authorize(READ_ROLES)
    items = list(db.sanitation_logs.values())
    station_id = request.args.get("station_id")
    if station_id is not None:
        items = [lg for lg in items if lg["station_id"] == station_id]
    tech_id = request.args.get("logged_by_technician_id")
    if tech_id is not None:
        items = [lg for lg in items if lg["logged_by_technician_id"] == tech_id]
    cr = request.args.get("cycle_result")
    if cr is not None:
        items = [lg for lg in items if lg["cycle_result"] == cr]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([sanitation_log_out(lg) for lg in page], limit, offset, total)


@bp.route("/sanitation-logs/<lid>", methods=["GET"])
def get_one_sanitation_log(lid):
    authorize(READ_ROLES)
    rec = get_sanitation_log(lid)
    return success_object(sanitation_log_out(rec), status=200)
