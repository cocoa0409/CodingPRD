from flask import Blueprint

from db import DB, _parse_iso, fmt_ts, stamp_new
from errors import not_found, validation
from middleware import (
    as_datetime_str,
    as_int,
    as_string,
    authenticate,
    get_json_body,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination
from services.core import check_window_overlap

bp = Blueprint("capacity_windows", __name__)


@bp.route("/capacity-windows", methods=["POST"])
def create_window():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["Planner"])
    label = as_string(body, "label")
    window_start = as_datetime_str(body, "window_start")
    window_end = as_datetime_str(body, "window_end")
    bay_hours_capacity = as_int(body, "bay_hours_capacity")
    if bay_hours_capacity is None or bay_hours_capacity <= 0:
        validation("bay_hours_capacity must be a positive integer")

    start_dt = _parse_iso(window_start)
    end_dt = _parse_iso(window_end)
    if end_dt <= start_dt:
        validation("window_end must be strictly later than window_start")

    check_window_overlap(start_dt, end_dt)

    window = stamp_new(
        {
            "label": label,
            "window_start": fmt_ts(start_dt),
            "window_end": fmt_ts(end_dt),
            "bay_hours_capacity": bay_hours_capacity,
            "bay_hours_reserved": 0,
            "window_posture": "NORMAL",
        }
    )
    DB.capacity_windows[window["id"]] = window
    return success_object(window, status=201)


@bp.route("/capacity-windows", methods=["GET"])
def list_windows():
    authenticate()
    limit, offset = parse_pagination()
    items = sorted(DB.capacity_windows.values(), key=lambda w: (w["created_at"], w["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/capacity-windows/<wid>", methods=["GET"])
def get_window(wid):
    authenticate()
    window = DB.capacity_windows.get(wid)
    if window is None:
        not_found("Capacity window not found")
    return success_object(window)
