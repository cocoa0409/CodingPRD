from flask import Blueprint, request

from db import db, common_create_fields
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.calc import MAX_WIND
from services.common import (
    get_body, require_fields, as_int, as_bool, parse_iso,
    get_route, get_weather_window,
    get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("weather", __name__)


def _intervals_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed intervals [a_start,a_end] and [b_start,b_end] overlap if they
    intersect at any point, including touching endpoints."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/weather-windows")
def create_weather_window():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["route_id", "window_start_utc", "window_end_utc", "wind_mph"])
    route = get_route(body["route_id"])
    start = parse_iso(body["window_start_utc"], "window_start_utc")
    end = parse_iso(body["window_end_utc"], "window_end_utc")
    wind = as_int(body["wind_mph"], "wind_mph", minimum=0)
    precip = False
    if "precip_flag" in body and body["precip_flag"] is not None:
        precip = as_bool(body["precip_flag"], "precip_flag")
    if not (end > start):
        raise ApiError("ERR_INVALID_REQUEST", "window_end_utc must be strictly after window_start_utc")

    # Closed-interval non-overlap on the same route (touching collides).
    for w in db.weather_windows.values():
        if w["route_id"] != route["id"]:
            continue
        w_start = parse_iso(w["window_start_utc"], "window_start_utc")
        w_end = parse_iso(w["window_end_utc"], "window_end_utc")
        if _intervals_overlap_closed(start, end, w_start, w_end):
            raise ApiError("ERR_WEATHER_WINDOW_OVERLAP", "Window overlaps an existing window on this route")

    condition = "BLOCKED" if (wind >= MAX_WIND or precip) else "CLEAR"
    w = common_create_fields()
    w.update({
        "route_id": route["id"],
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "wind_mph": wind,
        "condition": condition,
        "precip_flag": precip,
    })
    db.weather_windows[w["id"]] = w
    return success(serialize.weather_window_view(w), 201)


@bp.get("/weather-windows")
def list_weather_windows():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    route_id = request.args.get("route_id")
    limit, offset = get_pagination()
    items = [w for w in db.weather_windows.values()
             if route_id is None or w["route_id"] == route_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.weather_window_view(w) for w in page], limit, offset, total)


@bp.get("/weather-windows/<wid>")
def get_one_weather_window(wid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    w = get_weather_window(wid)
    return success(serialize.weather_window_view(w), 200)
