"""FaireDay endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import store, new_id, next_seq, clock_now
from errors import (
    ERR_FAIRE_DAY_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SEASON_INVALID_STATE,
    ERR_SEASON_POSTURE_BLOCKED,
    ERR_SEASON_NOT_OPEN,
    ERR_DAY_NOT_OPENABLE,
    ERR_DAY_NOT_HOLDABLE,
    ERR_DAY_NOT_ON_HOLD,
    ERR_DAY_NOT_CANCELLABLE,
    ERR_DAY_NOT_COMPLETABLE,
    ERR_OPEN_SHIFTS_EXIST,
    ERR_WEATHER_CALL_TOO_LATE,
    ERR_DAY_NOT_TODAY,
    ApiError,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import (
    cancel_faire_day_cascade,
    complete_faire_day_cascade,
    rederive_posture,
    tickets_sold_count,
    shifts_of_day,
    SHIFT_TERMINAL,
)
from util import req, check_unknown, new_record, mutate, public_view

bp = Blueprint("faire_days", __name__)

CREATE_FIELDS = {"season_id", "date"}


def day_view(day):
    return public_view(day, {"tickets_sold_count": tickets_sold_count(day)})


def load_day(did):
    return load(store.faire_days, did, ERR_FAIRE_DAY_NOT_FOUND, "faire day")


@bp.route("/faire-days", methods=["POST"])
def create_day():
    require_roles("FaireOperator")
    body = get_body()
    # Layer 3: body FK existence (season_id) before layer-4 shape.
    season_id = body.get("season_id")
    if isinstance(season_id, str):
        load(store.seasons, season_id, ERR_SEASON_NOT_FOUND, "season")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    season = load(store.seasons, season_id, ERR_SEASON_NOT_FOUND, "season")
    date = req(body, "date", "dt")
    if not (season["opening_date"] <= date <= season["closing_date"]):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "date must fall within [opening_date, closing_date]"
        )
    if season["status"] not in ("PLANNING", "BUILD"):
        raise conflict(
            ERR_SEASON_INVALID_STATE, "faire day scheduling requires PLANNING or BUILD"
        )
    day = new_record()
    day.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season["id"],
            "date": date,
            "status": "SCHEDULED",
        }
    )
    store.faire_days[day["id"]] = day
    return obj_response(day_view(day), 201)


@bp.route("/faire-days", methods=["GET"])
def list_days():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.faire_days),
        [("season_id", "season_id"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([day_view(d) for d in page], limit, offset, total)


@bp.route("/faire-days/<did>", methods=["GET"])
def get_day(did):
    require_roles()
    return obj_response(day_view(load_day(did)))


@bp.route("/faire-days/<did>/open-sales", methods=["POST"])
def open_sales(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] != "SCHEDULED":
        raise conflict(ERR_DAY_NOT_OPENABLE, "open-sales requires SCHEDULED")
    season = store.seasons[day["season_id"]]
    if season["status"] not in ("BUILD", "OPEN"):
        raise conflict(ERR_SEASON_INVALID_STATE, "open-sales requires season BUILD or OPEN")
    # Refresh the computed posture before reading the BLOCKED gate (§2.6, §3.6).
    rederive_posture(season)
    if season["readiness_posture"] == "BLOCKED":
        raise conflict(
            ERR_SEASON_POSTURE_BLOCKED, "open-sales forbidden while posture is BLOCKED"
        )
    mutate(day, status="OPEN_FOR_SALES")
    return obj_response(day_view(day))


@bp.route("/faire-days/<did>/weather-hold", methods=["POST"])
def weather_hold(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] != "OPEN_FOR_SALES":
        raise conflict(ERR_DAY_NOT_HOLDABLE, "weather-hold requires OPEN_FOR_SALES")
    mutate(day, status="WEATHER_HOLD")
    return obj_response(day_view(day))


@bp.route("/faire-days/<did>/release-hold", methods=["POST"])
def release_hold(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] != "WEATHER_HOLD":
        raise conflict(ERR_DAY_NOT_ON_HOLD, "release-hold requires WEATHER_HOLD")
    mutate(day, status="OPEN_FOR_SALES")
    return obj_response(day_view(day))


@bp.route("/faire-days/<did>/cancel-weather", methods=["POST"])
def cancel_weather(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] not in ("OPEN_FOR_SALES", "WEATHER_HOLD"):
        raise conflict(
            ERR_DAY_NOT_CANCELLABLE, "cancel-weather requires OPEN_FOR_SALES or WEATHER_HOLD"
        )
    season = store.seasons[day["season_id"]]
    deadline = day["date"] + timedelta(hours=season["weather_call_deadline_hour"])
    if not clock_now() < deadline:
        raise conflict(
            ERR_WEATHER_CALL_TOO_LATE,
            "cancel-weather must land before date + weather_call_deadline_hour hours",
        )
    cancel_faire_day_cascade(day, season)
    return obj_response(day_view(day))


@bp.route("/faire-days/<did>/open-gates", methods=["POST"])
def open_gates(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] != "OPEN_FOR_SALES":
        raise conflict(ERR_DAY_NOT_OPENABLE, "open-gates requires OPEN_FOR_SALES")
    season = store.seasons[day["season_id"]]
    if season["status"] != "OPEN":
        raise conflict(ERR_SEASON_NOT_OPEN, "open-gates requires season OPEN")
    if clock_now().date() != day["date"].date():
        raise conflict(ERR_DAY_NOT_TODAY, "open-gates only on the faire day's calendar date")
    mutate(day, status="OPERATING")
    return obj_response(day_view(day))


@bp.route("/faire-days/<did>/complete", methods=["POST"])
def complete_day(did):
    require_roles("FaireOperator")
    day = load_day(did)
    check_unknown(get_body(), set())
    if day["status"] != "OPERATING":
        raise conflict(ERR_DAY_NOT_COMPLETABLE, "complete requires OPERATING")
    if any(s["status"] not in SHIFT_TERMINAL for s in shifts_of_day(day["id"])):
        raise conflict(
            ERR_OPEN_SHIFTS_EXIST, "complete requires all of the day's shifts terminal"
        )
    season = store.seasons[day["season_id"]]
    complete_faire_day_cascade(day, season)
    return obj_response(day_view(day))
