"""VolunteerShift endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SHIFT_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_FAIRE_DAY_NOT_FOUND,
    ERR_DAY_NOT_STAFFABLE,
    ERR_VOLUNTEER_SHIFT_OVERLAP,
    ERR_SHIFT_NOT_CONFIRMABLE,
    ERR_SHIFT_NOT_CLOSABLE,
    ERR_SHIFT_NOT_CANCELLABLE,
    ERR_DAY_NOT_OPERATING,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import adjust_volunteer_hours, rederive_posture
from util import req, check_unknown, new_record, mutate, public_view, hours_between

bp = Blueprint("volunteer_shifts", __name__)

ROLES = {"GATE", "PARKING", "TAVERN", "INFO", "BACKSTAGE"}
OUTCOMES = {"WORKED", "NO_SHOW"}
CREATE_FIELDS = {"season_id", "faire_day_id", "role", "start_time", "end_time"}
LIVE = {"SIGNED_UP", "CONFIRMED"}


def load_shift(sid):
    return load(store.shifts, sid, ERR_SHIFT_NOT_FOUND, "volunteer shift")


@bp.route("/volunteer-shifts", methods=["POST"])
def create_shift():
    uid, _ = require_roles("Volunteer")
    body = get_body()
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    if isinstance(body.get("faire_day_id"), str):
        load(store.faire_days, body["faire_day_id"], ERR_FAIRE_DAY_NOT_FOUND, "faire day")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    faire_day_id = req(body, "faire_day_id", "str")
    role = req(body, "role", "enum", enum=ROLES)
    start = req(body, "start_time", "dt")
    end = req(body, "end_time", "dt")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_time must be > start_time")

    day = store.faire_days[faire_day_id]
    if day["status"] not in ("SCHEDULED", "OPEN_FOR_SALES"):
        raise conflict(
            ERR_DAY_NOT_STAFFABLE, "sign-up requires the day SCHEDULED or OPEN_FOR_SALES"
        )
    for other in store.shifts.values():
        if other["volunteer_handle"] != uid or other["status"] not in LIVE:
            continue
        if start < other["end_time"] and other["start_time"] < end:
            raise conflict(
                ERR_VOLUNTEER_SHIFT_OVERLAP,
                "the volunteer already holds an overlapping live shift",
            )
    shift = new_record()
    shift.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "faire_day_id": faire_day_id,
            "volunteer_handle": uid,
            "role": role,
            "start_time": start,
            "end_time": end,
            "status": "SIGNED_UP",
            "hours": hours_between(start, end),
        }
    )
    store.shifts[shift["id"]] = shift
    return obj_response(public_view(shift), 201)


@bp.route("/volunteer-shifts", methods=["GET"])
def list_shifts():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.shifts),
        [
            ("season_id", "season_id"),
            ("faire_day_id", "faire_day_id"),
            ("volunteer_handle", "volunteer_handle"),
            ("status", "status"),
        ],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(s) for s in page], limit, offset, total)


@bp.route("/volunteer-shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_roles()
    return obj_response(public_view(load_shift(sid)))


@bp.route("/volunteer-shifts/<sid>/confirm", methods=["POST"])
def confirm_shift(sid):
    require_roles("VolunteerCoordinator")
    shift = load_shift(sid)
    check_unknown(get_body(), set())
    if shift["status"] != "SIGNED_UP":
        raise conflict(ERR_SHIFT_NOT_CONFIRMABLE, "confirm requires SIGNED_UP")
    mutate(shift, status="CONFIRMED")
    season = store.seasons.get(shift["season_id"])
    if season is not None:
        adjust_volunteer_hours(season, shift["hours"])
        rederive_posture(season)
    return obj_response(public_view(shift))


@bp.route("/volunteer-shifts/<sid>/close-out", methods=["POST"])
def close_out_shift(sid):
    require_roles("VolunteerCoordinator")
    shift = load_shift(sid)
    body = get_body()
    check_unknown(body, {"outcome"})
    outcome = req(body, "outcome", "enum", enum=OUTCOMES)
    if shift["status"] != "CONFIRMED":
        raise conflict(ERR_SHIFT_NOT_CLOSABLE, "close-out requires CONFIRMED")
    day = store.faire_days[shift["faire_day_id"]]
    if day["status"] not in ("OPERATING", "COMPLETED"):
        raise conflict(ERR_DAY_NOT_OPERATING, "close-out requires the day OPERATING or COMPLETED")
    mutate(shift, status=outcome)
    if outcome == "NO_SHOW":
        season = store.seasons.get(shift["season_id"])
        if season is not None:
            adjust_volunteer_hours(season, -shift["hours"])
            rederive_posture(season)
    return obj_response(public_view(shift))


@bp.route("/volunteer-shifts/<sid>/cancel", methods=["POST"])
def cancel_shift(sid):
    uid, role = require_roles("Volunteer", "VolunteerCoordinator")
    shift = load_shift(sid)
    if role == "Volunteer":
        require_owner(uid == shift["volunteer_handle"])
    check_unknown(get_body(), set())
    if shift["status"] not in ("SIGNED_UP", "CONFIRMED"):
        raise conflict(ERR_SHIFT_NOT_CANCELLABLE, "cancel requires SIGNED_UP or CONFIRMED")
    was_confirmed = shift["status"] == "CONFIRMED"
    mutate(shift, status="CANCELLED")
    if was_confirmed:
        season = store.seasons.get(shift["season_id"])
        if season is not None:
            adjust_volunteer_hours(season, -shift["hours"])
            rederive_posture(season)
    return obj_response(public_view(shift))
