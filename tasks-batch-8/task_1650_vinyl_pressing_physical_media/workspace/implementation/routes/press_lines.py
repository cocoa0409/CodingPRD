"""PressLine, PressSlot (maintenance), PlatingBath endpoints."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PRESS_LINE_NOT_FOUND,
    ERR_PLATING_BATH_NOT_FOUND, ERR_DUPLICATE_CODE,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services import scheduling
from services.constants import TONNAGE_CLASSES
from .releases import valid_date_str

bp = Blueprint("press_lines", __name__)


def get_line_or_404(line_id):
    line = db.press_lines.get(line_id)
    if not line:
        raise ApiError(ERR_PRESS_LINE_NOT_FOUND, "Press line id does not exist", 404)
    return line


def get_bath_or_404(bath_id):
    b = db.plating_baths.get(bath_id)
    if not b:
        raise ApiError(ERR_PLATING_BATH_NOT_FOUND, "Plating bath id does not exist", 404)
    return b


# --- Press lines ---------------------------------------------------------------

@bp.route("/press-lines", methods=["POST"])
def create_press_line():
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    body = request.get_json(silent=True) or {}

    line_code = body.get("line_code")
    tonnage_class = body.get("tonnage_class")
    hours_per_day = body.get("hours_per_day")
    daily_unit_capacity = body.get("daily_unit_capacity")

    if not isinstance(line_code, str) or not line_code:
        raise ApiError(ERR_INVALID_REQUEST, "line_code is required", 400)
    if tonnage_class not in TONNAGE_CLASSES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid tonnage_class", 400)
    if not isinstance(hours_per_day, int) or isinstance(hours_per_day, bool) or hours_per_day <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "hours_per_day must be a positive integer", 400)
    if not isinstance(daily_unit_capacity, int) or isinstance(daily_unit_capacity, bool) or daily_unit_capacity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "daily_unit_capacity must be a positive integer", 400)

    for line in db.press_lines.values():
        if line["line_code"] == line_code:
            raise ApiError(ERR_DUPLICATE_CODE, "line_code already exists", 409)

    now = db.timestamp_now()
    line = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "line_code": line_code,
        "tonnage_class": tonnage_class,
        "hours_per_day": hours_per_day,
        "daily_unit_capacity": daily_unit_capacity,
    }
    db.press_lines[line["id"]] = line
    return success_object(serializers.press_line(line), 201)


@bp.route("/press-lines", methods=["GET"])
def list_press_lines():
    get_auth()
    limit, offset = get_pagination()
    page, total = apply_pagination(list(db.press_lines.values()), limit, offset)
    return success_list([serializers.press_line(l) for l in page], limit, offset, total)


@bp.route("/press-lines/<lid>", methods=["GET"])
def get_press_line(lid):
    get_auth()
    return success_object(serializers.press_line(get_line_or_404(lid)))


@bp.route("/press-lines/<lid>/slots", methods=["GET"])
def line_slots(lid):
    get_auth()
    line = get_line_or_404(lid)
    limit, offset = get_pagination()
    date_filter = request.args.get("date")
    items = [s for s in db.press_slots.values() if s["press_line_id"] == line["id"]]
    if date_filter is not None:
        items = [s for s in items if s["date"] == date_filter]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.press_slot(s) for s in page], limit, offset, total)


@bp.route("/press-lines/<lid>/backlog", methods=["GET"])
def line_backlog(lid):
    get_auth()
    line = get_line_or_404(lid)
    return success_object(scheduling.compute_backlog(line))


@bp.route("/press-lines/<lid>/maintenance-windows", methods=["POST"])
def create_maintenance_window(lid):
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    line = get_line_or_404(lid)
    body = request.get_json(silent=True) or {}

    d = body.get("date")
    sh = body.get("start_hour")
    eh = body.get("end_hour")

    if not valid_date_str(d):
        raise ApiError(ERR_INVALID_REQUEST, "date must be yyyy-mm-dd", 400)
    scheduling.validate_maintenance_hours(line, sh, eh)
    scheduling.check_maintenance_conflicts(line, d, sh, eh)

    now = db.timestamp_now()
    slot = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_line_id": line["id"],
        "press_order_id": None,
        "slot_kind": "MAINTENANCE",
        "date": d,
        "start_hour": sh,
        "end_hour": eh,
        "planned_units": 0,
        "color_family": None,
        "freed": False,
    }
    db.press_slots[slot["id"]] = slot
    return success_object(serializers.press_slot(slot), 201)


# --- Plating baths --------------------------------------------------------------

@bp.route("/plating-baths", methods=["POST"])
def create_plating_bath():
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    body = request.get_json(silent=True) or {}

    bath_code = body.get("bath_code")
    rinse_gap = body.get("rinse_gap_minutes", 30)

    if not isinstance(bath_code, str) or not bath_code:
        raise ApiError(ERR_INVALID_REQUEST, "bath_code is required", 400)
    if not isinstance(rinse_gap, int) or isinstance(rinse_gap, bool) or rinse_gap < 0:
        raise ApiError(ERR_INVALID_REQUEST, "rinse_gap_minutes must be a non-negative integer", 400)

    for b in db.plating_baths.values():
        if b["bath_code"] == bath_code:
            raise ApiError(ERR_DUPLICATE_CODE, "bath_code already exists", 409)

    now = db.timestamp_now()
    bath = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "bath_code": bath_code,
        "rinse_gap_minutes": rinse_gap,
    }
    db.plating_baths[bath["id"]] = bath
    return success_object(serializers.plating_bath(bath), 201)


@bp.route("/plating-baths", methods=["GET"])
def list_plating_baths():
    get_auth()
    limit, offset = get_pagination()
    page, total = apply_pagination(list(db.plating_baths.values()), limit, offset)
    return success_list([serializers.plating_bath(b) for b in page], limit, offset, total)


@bp.route("/plating-baths/<bid>", methods=["GET"])
def get_plating_bath(bid):
    get_auth()
    return success_object(serializers.plating_bath(get_bath_or_404(bid)))


@bp.route("/plating-baths/<bid>/tooling-jobs", methods=["GET"])
def bath_tooling_jobs(bid):
    get_auth()
    bath = get_bath_or_404(bid)
    limit, offset = get_pagination()
    items = [j for j in db.tooling_jobs.values() if j.get("plating_bath_id") == bath["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.tooling_job(j) for j in page], limit, offset, total)
