"""Room seats: offers, responses and CASCADE B (PRD 3.3, 3.4)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, SHOWRUNNER, STUDIO_EXECUTIVE, WRITER,
                        fetch, require)
from response import created, ok
from routes.common import date_range, list_out, match, out
from services import calc, domain
from validation import (body_json, filter_value, raw, v_bool, v_dt, v_enum, v_int,
                        v_str)

bp = Blueprint("seats", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, WRITER)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap (PRD 2.8)."""
    return a_start < b_end and b_start < a_end


def _containing_windows(writer_id, start, end):
    rows = [w for w in domain.windows_of(writer_id)
            if w["status"] == "OPEN"
            and w["start_date"] <= start and end <= w["end_date"]]
    rows.sort(key=lambda w: (w["start_date"], w["created_at"], w["_seq"]))
    return rows


@bp.post("/rooms/<room_id>/seats")
def offer_seat(room_id):
    actor = require(SHOWRUNNER)
    room = fetch(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    season = domain.season_of_room(room)
    agreement = domain.agreement_of(season)
    body = body_json()
    writer_ref = raw(body, "writer_id")
    writer = None
    if writer_ref is not None:
        writer = fetch(db.writers, writer_ref, "ERR_WRITER_NOT_FOUND")
    row = base_row()
    row["level_at_hire"] = v_enum(body, "level_at_hire", calc.LEVELS)
    row["offered_weekly_compensation_cents"] = v_int(
        body, "offered_weekly_compensation_cents", lo=1)
    row["exclusivity"] = v_enum(body, "exclusivity", calc.COMMITMENT_TYPES)
    start = v_dt(body, "start_date")
    end = v_dt(body, "end_date")
    row["episodic_guarantee_count"] = v_int(
        body, "episodic_guarantee_count", 0, 30, required=False, default=0)
    row["diversity_program_funded"] = v_bool(
        body, "diversity_program_funded", required=False, default=False)
    expected = v_int(body, "expected_room_version")
    if writer is None:
        raise ApiError("ERR_INVALID_REQUEST")
    date_range(start, end)
    # 13. optimistic concurrency, then 14. room state (PRD 2.11)
    if expected != room["version"]:
        raise ApiError("ERR_STALE_ROOM_VERSION")
    if room["status"] != "STAFFING":
        raise ApiError("ERR_ROOM_NOT_ACCEPTING_SEATS")
    # 16. domain safety: guild floor, level, diversity funding
    minimum = agreement["min_weekly_cents_by_level"][row["level_at_hire"]]
    if row["offered_weekly_compensation_cents"] < minimum:
        raise ApiError("ERR_BELOW_GUILD_MINIMUM")
    seat_rank = calc.LEVELS.index(row["level_at_hire"])
    writer_rank = calc.LEVELS.index(writer["determined_level"])
    allowance = 1 if row["diversity_program_funded"] else 0
    if seat_rank > writer_rank + allowance:
        raise ApiError("ERR_LEVEL_ABOVE_DETERMINED")
    if row["diversity_program_funded"] and not writer["diversity_program_participant"]:
        raise ApiError("ERR_DIVERSITY_FUNDING_INELIGIBLE")
    # 17. temporal: the offer must start inside the staffing window
    if start < season["staffing_window_start"] or start > season["staffing_window_end"]:
        raise ApiError("ERR_OUTSIDE_STAFFING_WINDOW")
    # 18. structural: writer interval exclusivity, availability, capacity
    for other in domain.seats_of_writer(writer["id"]):
        if other["status"] not in ("OFFERED", "CONFIRMED"):
            continue
        if not _overlaps(start, end, other["start_date"], other["end_date"]):
            continue
        if other["exclusivity"] == "EXCLUSIVE" or row["exclusivity"] == "EXCLUSIVE":
            raise ApiError("ERR_WRITER_WINDOW_CONFLICT")
    if not _containing_windows(writer["id"], start, end):
        raise ApiError("ERR_WRITER_UNAVAILABLE")
    if room["open_seat_count"] < 1:
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")
    row["room_id"] = room["id"]
    row["writer_id"] = writer["id"]
    row["start_date"] = start
    row["end_date"] = end
    calc.seat_weekly_compensation(row, room, writer, agreement)
    calc.seat_prorated_commitment(row)
    # 20. fiscal ceiling: the season staffing budget
    projected = (season["staffing_commitment_weekly_cents"]
                 + row["weekly_compensation_cents"])
    if projected > season["staffing_budget_weekly_cents"]:
        raise ApiError("ERR_SEASON_STAFFING_BUDGET_EXCEEDED")
    row["guarantee_slots_consumed"] = 0
    row["guarantee_slots_remaining"] = row["episodic_guarantee_count"]
    row["status"] = "OFFERED"
    row["confirmed_at"] = None
    row["consumed_window_id"] = None
    db.seats[row["id"]] = row
    writer["active_seat_count"] += 1
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return created(out(row))


def _seat_context(seat):
    room = db.rooms[seat["room_id"]]
    return room, domain.season_of_room(room)


@bp.post("/room-seats/<seat_id>/accept")
def accept_seat(seat_id):
    actor = require(WRITER)
    seat = fetch(db.seats, seat_id, "ERR_SEAT_NOT_FOUND")
    room, season = _seat_context(seat)
    # 11. ownership, then 14. state, then 18. availability containment
    if seat["writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if seat["status"] != "OFFERED":
        raise ApiError("ERR_SEAT_NOT_OFFERED")
    if room["status"] != "STAFFING":
        raise ApiError("ERR_ROOM_NOT_ACCEPTING_SEATS")
    candidates = _containing_windows(seat["writer_id"], seat["start_date"], seat["end_date"])
    if not candidates:
        raise ApiError("ERR_WRITER_UNAVAILABLE")
    window = candidates[0]
    seat["status"] = "CONFIRMED"
    seat["confirmed_at"] = db.now()
    seat["consumed_window_id"] = window["id"]
    touch(seat)
    window["status"] = "CONSUMED"
    window["consumed_by_seat_id"] = seat["id"]
    touch(window)
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return ok(out(seat))


@bp.post("/room-seats/<seat_id>/decline")
def decline_seat(seat_id):
    actor = require(WRITER)
    seat = fetch(db.seats, seat_id, "ERR_SEAT_NOT_FOUND")
    room, season = _seat_context(seat)
    body = body_json()
    v_str(body, "reason", 1, 500, required=False)
    if seat["writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if seat["status"] != "OFFERED":
        raise ApiError("ERR_SEAT_NOT_OFFERED")
    return _retire_offer(seat, room, season, "DECLINED")


@bp.post("/room-seats/<seat_id>/withdraw")
def withdraw_seat(seat_id):
    require(SHOWRUNNER)
    seat = fetch(db.seats, seat_id, "ERR_SEAT_NOT_FOUND")
    room, season = _seat_context(seat)
    body = body_json()
    v_str(body, "reason", 1, 500, required=False)
    if seat["status"] != "OFFERED":
        raise ApiError("ERR_SEAT_NOT_OFFERED")
    return _retire_offer(seat, room, season, "WITHDRAWN")


def _retire_offer(seat, room, season, status):
    seat["status"] = status
    touch(seat)
    writer = db.writers.get(seat["writer_id"])
    if writer is not None and writer["active_seat_count"] > 0:
        writer["active_seat_count"] -= 1
    domain.recompute_room(room)
    domain.recompute_season_commitment(season)
    touch(room)
    return ok(out(seat))


@bp.post("/room-seats/<seat_id>/release")
def release(seat_id):
    require(STUDIO_EXECUTIVE, SHOWRUNNER)
    seat = fetch(db.seats, seat_id, "ERR_SEAT_NOT_FOUND")
    room, season = _seat_context(seat)
    body = body_json()
    v_str(body, "reason", 1, 500, required=False)
    if seat["status"] != "CONFIRMED":
        raise ApiError("ERR_SEAT_NOT_CONFIRMED")
    domain.release_seat(seat, room, season)
    touch(room)
    return ok(out(seat))


@bp.get("/room-seats/<seat_id>")
def get_seat(seat_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.seats, seat_id, "ERR_SEAT_NOT_FOUND")))


@bp.get("/room-seats")
def list_seats():
    require(*READ_ROLES)
    rows = list(db.seats.values())
    rows = match(rows, "room_id", filter_value("room_id"))
    rows = match(rows, "writer_id", filter_value("writer_id"))
    rows = match(rows, "consumed_window_id", filter_value("consumed_window_id"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)
