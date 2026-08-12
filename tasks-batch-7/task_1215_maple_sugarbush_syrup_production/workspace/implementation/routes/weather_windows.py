"""WeatherWindow endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_str,
                  as_number, parse_dt, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_OUTSIDE_PRODUCTION_WINDOW,
                    ERR_WINDOW_OVERLAP, ERR_NO_FREEZE_THAW,
                    ERR_SEASON_NOT_OPEN, ERR_SEASON_SUSPENDED)
from services import core

bp = Blueprint("weather_windows", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_window_or_404(wid):
    w = db.weather_windows.get(wid)
    if not w:
        raise_err(ERR_NOT_FOUND, f"weather window {wid} not found")
    return w


@bp.post("/sugarhouse/weather-windows")
def create_window():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    allowed = {"season_id", "opens_at", "closes_at", "forecast_min_f", "forecast_max_f",
               "expected_season_version"}
    check_unknown_fields(data, allowed)
    require_fields(data, ["season_id", "opens_at", "closes_at", "forecast_min_f",
                          "forecast_max_f", "expected_season_version"])
    season_id = as_str(data["season_id"], "season_id")
    season = db.seasons.get(season_id)
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {season_id} not found")
    # OCC (priority 4) — priority order: existence (3) then OCC (4)
    expected = data["expected_season_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_VALIDATION, "expected_season_version must be an integer")
    if expected != season["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_season_version {expected} != current {season['version']}")

    # Parse instants
    try:
        opens_dt = parse_dt(data["opens_at"])
        closes_dt = parse_dt(data["closes_at"])
    except Exception:
        raise_err(ERR_VALIDATION, "opens_at/closes_at must be ISO8601 datetimes")
    forecast_min_f = as_number(data["forecast_min_f"], "forecast_min_f")
    forecast_max_f = as_number(data["forecast_max_f"], "forecast_max_f")
    if closes_dt <= opens_dt:
        raise_err(ERR_VALIDATION, "closes_at must be strictly after opens_at")

    # Priority 8 structural: freeze-thaw + overlap
    if not (forecast_min_f <= core.FREEZE_F and forecast_max_f >= core.THAW_F):
        raise_err(ERR_NO_FREEZE_THAW,
                  "forecast_min_f must be <= 32.0 and forecast_max_f >= 38.0")
    for other in db.weather_windows.values():
        if other["season_id"] != season["id"]:
            continue
        if other["status"] not in ("FORECAST", "OPEN"):
            continue
        o = parse_dt(other["opens_at"])
        c = parse_dt(other["closes_at"])
        # half-open overlap: [o,c) intersect [opens,closes) iff opens < c and o < closes
        if opens_dt < c and o < closes_dt:
            raise_err(ERR_WINDOW_OVERLAP,
                      "new window overlaps an existing FORECAST/OPEN window")

    from util import fmt_dt
    w = core.new_weather_window(
        season_id=season_id,
        opens_at=fmt_dt(opens_dt),
        closes_at=fmt_dt(closes_dt),
        forecast_min_f=forecast_min_f,
        forecast_max_f=forecast_max_f,
    )
    db.weather_windows[w["id"]] = w
    # Declaration increments season version (PRD §2.6 / §3.3)
    core.bump(season)
    return success_object(core.ser_weather_window(w), status=201)


@bp.get("/sugarhouse/weather-windows/<wid>")
def get_window(wid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    w = get_window_or_404(wid)
    return success_object(core.ser_weather_window(w))


@bp.get("/sugarhouse/weather-windows")
def list_windows():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    rows = list(db.weather_windows.values())
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_weather_window(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/weather-windows/<wid>/open")
def open_window(wid):
    caller = authenticate()
    require_role(caller, MGR)
    w = get_window_or_404(wid)
    if w["status"] != "FORECAST":
        raise_err(ERR_INVALID_STATE, f"window is {w['status']}, expected FORECAST")
    season = db.seasons.get(w["season_id"])
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {w['season_id']} not found")
    # Priority 5: season state (with SUSPENDED split)
    if season["status"] == "SUSPENDED":
        raise_err(ERR_SEASON_SUSPENDED, "season is SUSPENDED")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_OPEN, f"season is {season['status']}, expected OPEN")
    # Priority 7: clock within [opens_at, closes_at)
    now = core.clock_dt()
    o = parse_dt(w["opens_at"])
    c = parse_dt(w["closes_at"])
    if not (o <= now < c):
        raise_err(ERR_OUTSIDE_PRODUCTION_WINDOW,
                  "logical clock outside window [opens_at, closes_at)")
    w["status"] = "OPEN"
    core.bump(w)
    return success_object(core.ser_weather_window(w))
