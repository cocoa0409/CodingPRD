"""Season endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ERR_SEASON_NOT_FOUND,
    ERR_SEASON_NOT_IN_PLANNING,
    ERR_SEASON_INVALID_STATE,
    ERR_SEASON_NOT_READY,
    ERR_UNRESOLVED_FAIRE_DAYS,
    ERR_UNSETTLED_BOOTHS,
    ERR_STRIKE_TASKS_INCOMPLETE,
    ERR_STALE_VERSION,
    ApiError,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import (
    rederive_posture,
    season_open_cascade,
    season_strike_cascade,
    season_close_sweep,
    DAY_TERMINAL,
)
from util import (
    req,
    opt,
    check_unknown,
    new_record,
    mutate,
    assign,
    touch,
    ceil_weeks,
    public_view,
)

bp = Blueprint("seasons", __name__)

SEASON_FIELDS = {
    "name",
    "opening_date",
    "closing_date",
    "daily_capacity",
    "group_min_size",
    "volunteer_min_hours",
    "weather_call_deadline_hour",
    "rain_check_grace_days",
}

PATCH_FIELDS = {
    "expected_season_version",
    "daily_capacity",
    "group_min_size",
    "volunteer_min_hours",
    "weather_call_deadline_hour",
    "rain_check_grace_days",
}


def season_view(season):
    return public_view(season)


@bp.route("/seasons", methods=["POST"])
def create_season():
    require_roles("FaireOperator")
    body = get_body()
    check_unknown(body, SEASON_FIELDS)
    name = req(body, "name", "str")
    opening = req(body, "opening_date", "dt")
    closing = req(body, "closing_date", "dt")
    if closing < opening:
        raise ApiError("ERR_INVALID_REQUEST", 400, "closing_date must be >= opening_date")
    daily_capacity = req(body, "daily_capacity", "int", lo=1)
    group_min_size = req(body, "group_min_size", "int", lo=2)
    volunteer_min_hours = req(body, "volunteer_min_hours", "num", lo=0)
    weather_call_deadline_hour = req(body, "weather_call_deadline_hour", "int", lo=0, hi=23)
    rain_check_grace_days = req(body, "rain_check_grace_days", "int", lo=0)

    season = new_record()
    season.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "name": name,
            "status": "PLANNING",
            "readiness_posture": "BLOCKED",
            "opening_date": opening,
            "closing_date": closing,
            "daily_capacity": daily_capacity,
            "group_min_size": group_min_size,
            "volunteer_min_hours": volunteer_min_hours,
            "weather_call_deadline_hour": weather_call_deadline_hour,
            "rain_check_grace_days": rain_check_grace_days,
            "volunteer_confirmed_hours": Decimal(0),
            "outstanding_admissions": 0,
            "season_weeks": ceil_weeks(opening, closing),
        }
    )
    store.seasons[season["id"]] = season
    return obj_response(season_view(season), 201)


@bp.route("/seasons", methods=["GET"])
def list_seasons():
    require_roles()
    limit, offset = parse_pagination()
    items = sorted_by_creation(store.seasons)
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([season_view(s) for s in page], limit, offset, total)


def load_season(sid):
    return load(store.seasons, sid, ERR_SEASON_NOT_FOUND, "season")


@bp.route("/seasons/<sid>", methods=["GET"])
def get_season(sid):
    require_roles()
    return obj_response(season_view(load_season(sid)))


@bp.route("/seasons/<sid>", methods=["PATCH"])
def patch_season(sid):
    require_roles("FaireOperator")
    season = load_season(sid)
    body = get_body()
    check_unknown(body, PATCH_FIELDS)
    expected = req(body, "expected_season_version", "int")
    changes = {}
    if "daily_capacity" in body and body["daily_capacity"] is not None:
        changes["daily_capacity"] = req(body, "daily_capacity", "int", lo=1)
    if "group_min_size" in body and body["group_min_size"] is not None:
        changes["group_min_size"] = req(body, "group_min_size", "int", lo=2)
    if "volunteer_min_hours" in body and body["volunteer_min_hours"] is not None:
        changes["volunteer_min_hours"] = req(body, "volunteer_min_hours", "num", lo=0)
    if "weather_call_deadline_hour" in body and body["weather_call_deadline_hour"] is not None:
        changes["weather_call_deadline_hour"] = req(
            body, "weather_call_deadline_hour", "int", lo=0, hi=23
        )
    if "rain_check_grace_days" in body and body["rain_check_grace_days"] is not None:
        changes["rain_check_grace_days"] = req(body, "rain_check_grace_days", "int", lo=0)

    # Layer 5: state gate, then OCC version check (last within the layer).
    if season["status"] != "PLANNING":
        raise conflict(ERR_SEASON_NOT_IN_PLANNING, "season configuration edits require PLANNING")
    if expected != season["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_season_version does not match current version")

    hours_changed = "volunteer_min_hours" in changes and changes[
        "volunteer_min_hours"
    ] != season["volunteer_min_hours"]
    assign(season, **changes)
    touch(season)  # a successful edit increments version by exactly 1
    if hours_changed:
        rederive_posture(season)
    return obj_response(season_view(season))


@bp.route("/seasons/<sid>/begin-build", methods=["POST"])
def begin_build(sid):
    require_roles("FaireOperator")
    season = load_season(sid)
    check_unknown(get_body(), set())
    if season["status"] != "PLANNING":
        raise conflict(ERR_SEASON_NOT_IN_PLANNING, "begin-build requires PLANNING")
    mutate(season, status="BUILD")
    # The posture is a computed field (§2.6); refresh the stored value on the
    # season transition so the gates downstream read the current derivation.
    rederive_posture(season)
    return obj_response(season_view(season))


@bp.route("/seasons/<sid>/open", methods=["POST"])
def open_season(sid):
    require_roles("FaireOperator")
    season = load_season(sid)
    check_unknown(get_body(), set())
    if season["status"] != "BUILD":
        raise conflict(ERR_SEASON_INVALID_STATE, "open requires BUILD")
    # Refresh the computed posture before reading the READY gate (§2.6, §3.1).
    rederive_posture(season)
    if season["readiness_posture"] != "READY":
        raise conflict(ERR_SEASON_NOT_READY, "open requires readiness_posture READY")
    mutate(season, status="OPEN")
    season_open_cascade(season)
    return obj_response(season_view(season))


@bp.route("/seasons/<sid>/begin-strike", methods=["POST"])
def begin_strike(sid):
    require_roles("FaireOperator")
    season = load_season(sid)
    check_unknown(get_body(), set())
    if season["status"] != "OPEN":
        raise conflict(ERR_SEASON_INVALID_STATE, "begin-strike requires OPEN")
    unresolved = any(
        d["status"] not in DAY_TERMINAL
        for d in store.faire_days.values()
        if d["season_id"] == season["id"]
    )
    if unresolved:
        raise conflict(
            ERR_UNRESOLVED_FAIRE_DAYS,
            "begin-strike requires every faire day COMPLETED or CANCELLED_WEATHER",
        )
    mutate(season, status="STRIKE")
    season_strike_cascade(season)
    return obj_response(season_view(season))


@bp.route("/seasons/<sid>/close", methods=["POST"])
def close_season(sid):
    require_roles("FaireOperator")
    season = load_season(sid)
    check_unknown(get_body(), set())
    if season["status"] != "STRIKE":
        raise conflict(ERR_SEASON_INVALID_STATE, "close requires STRIKE")
    unsettled = any(
        b["status"] not in ("SETTLED", "RELEASED")
        for b in store.booths.values()
        if b["season_id"] == season["id"]
    )
    if unsettled:
        raise conflict(
            ERR_UNSETTLED_BOOTHS,
            "close requires every booth assignment SETTLED or RELEASED",
        )
    incomplete = any(
        t["phase"] == "STRIKE" and t["status"] != "DONE"
        for t in store.tasks.values()
        if t["season_id"] == season["id"]
    )
    if incomplete:
        raise conflict(
            ERR_STRIKE_TASKS_INCOMPLETE, "close requires all STRIKE-phase tasks DONE"
        )
    mutate(season, status="CLOSED")
    season_close_sweep(season)
    return obj_response(season_view(season))
