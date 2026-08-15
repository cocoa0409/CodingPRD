"""FieldDayWindow endpoints (PRD §3.3)."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_DATE_OUTSIDE_SEASON,
    ERR_INVALID_REQUEST,
    ERR_DAY_NOT_OPEN,
    ERR_FIELD_NOT_OPEN,
    ERR_INSUFFICIENT_STAFFING,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OUTSIDE_WINDOW_HOURS,
    ERR_SEASON_NOT_ACTIVE,
    ERR_WINDOW_OVERLAP,
)
from helpers import (
    ceil_div,
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_date,
    req_int,
    req_str,
    req_time,
    require,
)

bp = Blueprint("windows", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff")


@bp.post("/farm/field-day-windows")
def create_window():
    require(FM)
    body = get_body()
    check_no_undeclared(
        body, {"field_id", "date", "open_time", "close_time", "picking_capacity_slots"}
    )
    field_id = req_str(body, "field_id")
    date = req_date(body, "date")
    open_time = req_time(body, "open_time")
    close_time = req_time(body, "close_time")
    capacity = req_int(body, "picking_capacity_slots", min_value=1)
    if close_time <= open_time:
        raise_err(ERR_INVALID_REQUEST, "close_time must be strictly after open_time")
    field = db.fields.get(field_id)
    if field is None:
        raise_err(ERR_NOT_FOUND, "field_id does not resolve")
    season = domain.season_of_field(field)
    if season is None or season["status"] != "ACTIVE":
        raise_err(ERR_SEASON_NOT_ACTIVE, "Season of the field is not ACTIVE")
    if not (season["start_date"] <= date <= season["end_date"]):
        raise_err(ERR_DATE_OUTSIDE_SEASON, "Window date is outside the season range")
    for w in db.windows.values():
        if (
            w["field_id"] == field_id
            and w["date"] == date
            and w["status"] != "CANCELLED"
            and open_time < w["close_time"]
            and w["open_time"] < close_time
        ):
            raise_err(ERR_WINDOW_OVERLAP, "Window overlaps an existing window")
    day = domain.sales_day_for(field["season_id"], date)
    if day is not None:
        total_slots = capacity + sum(
            w["picking_capacity_slots"]
            for w in db.windows.values()
            if (f := db.fields.get(w["field_id"])) is not None
            and f["season_id"] == field["season_id"]
            and w["date"] == date
            and w["status"] != "CANCELLED"
        )
        required_staff = ceil_div(total_slots, domain.STAFF_COVERAGE_SLOTS_PER_STAFF)
        if day["staff_on_duty"] < required_staff:
            raise_err(ERR_INSUFFICIENT_STAFFING, "Insufficient staff_on_duty for the day's slots")
    window = domain.new_entity()
    window.update(
        {
            "field_id": field_id,
            "date": date,
            "open_time": open_time,
            "close_time": close_time,
            "picking_capacity_slots": capacity,
            "status": "SCHEDULED",
            "cancel_reason": None,
        }
    )
    db.windows[window["id"]] = window
    return ok_object(domain.serialize_window(window), 201)


@bp.get("/farm/field-day-windows/<wid>")
def get_window(wid):
    require(READERS)
    window = db.windows.get(wid)
    if window is None:
        raise_err(ERR_NOT_FOUND, "Window not found")
    return ok_object(domain.serialize_window(window))


@bp.get("/farm/field-day-windows")
def list_windows():
    require(READERS)
    items = list(db.windows.values())
    field_id = request.args.get("field_id")
    if field_id is not None:
        items = [w for w in items if w["field_id"] == field_id]
    date = request.args.get("date")
    if date is not None:
        items = [w for w in items if w["date"] == date]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return paginate(items, domain.serialize_window)


@bp.post("/farm/field-day-windows/<wid>/open")
def open_window(wid):
    require(FM)
    window = db.windows.get(wid)
    if window is None:
        raise_err(ERR_NOT_FOUND, "Window not found")
    if window["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED window can be opened")
    season = domain.season_of_window(window)
    if season is None or season["status"] != "ACTIVE":
        raise_err(ERR_SEASON_NOT_ACTIVE, "Season is not ACTIVE")
    field = domain.field_of_window(window)
    if field is None or field["status"] != "OPEN":
        raise_err(ERR_FIELD_NOT_OPEN, "Field of the window is not OPEN")
    day = domain.sales_day_for(season["id"], window["date"])
    if day is None or day["status"] != "OPEN":
        raise_err(ERR_DAY_NOT_OPEN, "SalesDay of the window's date is not OPEN")
    now_date = db.logical_date_str()
    now_hhmm = db.logical_hhmm_str()
    if not (
        now_date == window["date"]
        and window["open_time"] <= now_hhmm < window["close_time"]
    ):
        raise_err(ERR_OUTSIDE_WINDOW_HOURS, "Logical clock is outside the window hours")
    window["status"] = "OPEN"
    domain.touch(window)
    return ok_object(domain.serialize_window(window))


@bp.post("/farm/field-day-windows/<wid>/cancel")
def cancel_window(wid):
    require(FM)
    window = db.windows.get(wid)
    if window is None:
        raise_err(ERR_NOT_FOUND, "Window not found")
    if window["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED window can be manually cancelled")
    if domain.window_booked_slots(window) != 0:
        raise_err(ERR_INVALID_STATE, "Window has bookings")
    window["status"] = "CANCELLED"
    window["cancel_reason"] = "MANUAL"
    domain.touch(window)
    return ok_object(domain.serialize_window(window))
