"""Writers rooms: configuration, staffing posture and CASCADE C (PRD 3.3, 3.4)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, LEGAL_COUNSEL, SHOWRUNNER,
                        STUDIO_EXECUTIVE, WRITER, fetch, require)
from response import created, ok
from routes.common import date_range, list_out, match, out
from services import calc, domain
from validation import body_json, filter_value, v_dt, v_enum, v_int, v_str

bp = Blueprint("rooms", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, LEGAL_COUNSEL, WRITER)


@bp.post("/seasons/<season_id>/rooms")
def create_room(season_id):
    require(SHOWRUNNER, STUDIO_EXECUTIVE)
    season = fetch(db.seasons, season_id, "ERR_SEASON_NOT_FOUND")
    body = body_json()
    row = base_row()
    row["name"] = v_str(body, "name", 1, 120)
    row["format"] = v_enum(body, "format", calc.ROOM_FORMATS)
    row["seat_capacity"] = v_int(body, "seat_capacity", 1, 12)
    row["duration_weeks_committed"] = v_int(body, "duration_weeks_committed", 1, 52)
    start = v_dt(body, "start_date")
    end = v_dt(body, "end_date")
    required = v_int(body, "diversity_seats_required", lo=0, required=False, default=0)
    if required > row["seat_capacity"]:
        raise ApiError("ERR_INVALID_REQUEST")
    row["diversity_seats_required"] = required
    date_range(start, end)
    # the room must open inside the staffing-window-to-photography span (PRD 3.3)
    if start < season["staffing_window_start"] or start > season["production_start_date"]:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    if row["format"] == "MINI_ROOM" and row["seat_capacity"] > 4:
        raise ApiError("ERR_MINI_ROOM_SEAT_LIMIT")
    row["season_id"] = season["id"]
    row["start_date"] = start
    row["end_date"] = end
    row["status"] = "OPEN"
    row["filled_seat_count"] = 0
    row["confirmed_seat_count"] = 0
    row["open_seat_count"] = row["seat_capacity"]
    row["confirmed_diversity_seat_count"] = 0
    row["seat_subtotal_weekly_cents"] = 0
    row["facility_tier"] = "TIER_1"
    row["facility_surcharge_weekly_cents"] = 0
    row["weekly_burn_cents"] = 0
    db.rooms[row["id"]] = row
    domain.recompute_room(row)
    return created(out(row))


@bp.post("/rooms/<room_id>/open-staffing")
def open_staffing(room_id):
    require(SHOWRUNNER)
    room = fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    season = domain.season_of_room(room)
    if room["status"] != "OPEN":
        raise ApiError("ERR_ROOM_NOT_ACCEPTING_SEATS")
    if db.now() > season["staffing_window_end"]:
        raise ApiError("ERR_STAFFING_WINDOW_CLOSED")
    room["status"] = "STAFFING"
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return ok(out(room))


@bp.post("/rooms/<room_id>/reconfigure")
def reconfigure(room_id):
    require(STUDIO_EXECUTIVE)
    room = fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    season = domain.season_of_room(room)
    body = body_json()
    new_format = v_enum(body, "format", calc.ROOM_FORMATS)
    new_duration = v_int(body, "duration_weeks_committed", 1, 52)
    expected = v_int(body, "expected_room_version")
    # PRD 2.11: optimistic concurrency precedes every state and domain check
    if expected != room["version"]:
        raise ApiError("ERR_STALE_ROOM_VERSION")
    if room["status"] != "STAFFING":
        raise ApiError("ERR_ROOM_NOT_ACCEPTING_SEATS")
    if new_format == "MINI_ROOM" and (room["seat_capacity"] > 4
                                     or room["filled_seat_count"] > 4):
        raise ApiError("ERR_MINI_ROOM_SEAT_LIMIT")
    domain.reconfigure_room(room, new_format, new_duration, season)
    touch(room)
    return ok(out(room))


@bp.post("/rooms/<room_id>/activate")
def activate(room_id):
    require(STUDIO_EXECUTIVE)
    room = fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    season = domain.season_of_room(room)
    if room["status"] != "STAFFING":
        raise ApiError("ERR_ROOM_NOT_ACCEPTING_SEATS")
    seats = domain.seats_of(room["id"])
    if any(s["status"] == "OFFERED" for s in seats):
        raise ApiError("ERR_SEATS_STILL_OFFERED")
    if room["confirmed_seat_count"] < 1:
        raise ApiError("ERR_ROOM_HAS_NO_CONFIRMED_SEATS")
    if room["confirmed_diversity_seat_count"] < room["diversity_seats_required"]:
        raise ApiError("ERR_DIVERSITY_REQUIREMENT_UNMET")
    if season["staffing_commitment_weekly_cents"] > season["staffing_budget_weekly_cents"]:
        raise ApiError("ERR_SEASON_STAFFING_BUDGET_EXCEEDED")
    room["status"] = "ACTIVE"
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return ok(out(room))


@bp.post("/rooms/<room_id>/wrap")
def wrap(room_id):
    require(SHOWRUNNER, STUDIO_EXECUTIVE)
    room = fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    season = domain.season_of_room(room)
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_NOT_ACTIVE")
    room["status"] = "WRAPPED"
    for seat in domain.seats_of(room["id"]):
        if seat["status"] == "CONFIRMED":
            domain.release_seat(seat, room, season)
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return ok(out(room))


@bp.get("/rooms/<room_id>")
def get_room(room_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")))


@bp.get("/rooms")
def list_rooms():
    require(*READ_ROLES)
    rows = list(db.rooms.values())
    rows = match(rows, "season_id", filter_value("season_id"))
    rows = match(rows, "format", filter_value("format"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)
