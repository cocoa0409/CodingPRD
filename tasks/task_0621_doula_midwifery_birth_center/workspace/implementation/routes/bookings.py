"""Booking routes: hold (OCC + overlap), confirm, check-in, cancel."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from common import (stamp_new, touch, public, paginate, get_body,
                    require_string, require_int, require_datetime, parse_dt)
from errors import (err, ERR_INVALID_STATE, ERR_INVALID_INTERVAL,
                    ERR_ROOM_DOUBLE_BOOKED, ERR_STALE_VERSION)
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response, array_response
import lookup

bp = Blueprint("bookings", __name__)

# Non-terminal booking statuses occupy the room (terminal: COMPLETED,
# TRANSFERRED, CANCELLED).
_NON_TERMINAL = ("HELD", "CONFIRMED", "IN_USE")


@bp.route("/birth-center/bookings", methods=["POST"])
def create_booking():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    room_id = require_string(body, "room_id")
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    expected_room_version = require_int(body, "expected_room_version")
    lookup.get_episode(episode_id)
    room = lookup.get_room(room_id)

    s_new = parse_dt(starts_at, "starts_at")
    e_new = parse_dt(ends_at, "ends_at")

    # OCC (priority 21) sits at the tail of the foundational order, after
    # existence; the interval/overlap business checks have their own priorities
    # (12, 13). Order them so the more-specific business error surfaces: well-
    # formed interval (13, 422) then overlap (12, 409), then stale version (21).
    # Interval well-formedness (priority 13).
    if not (s_new < e_new):
        raise err(ERR_INVALID_INTERVAL, "starts_at must be strictly before ends_at")

    # Room double-booking with turnover buffer (priority 12), half-open semantics.
    turnover = timedelta(minutes=room.get("turnover_minutes", 0))
    for b in db.bookings.values():
        if b["room_id"] != room_id:
            continue
        if b["status"] not in _NON_TERMINAL:
            continue
        s_old = parse_dt(b["starts_at"], "starts_at")
        e_old = parse_dt(b["ends_at"], "ends_at")
        # Each booking blocks [start, end + turnover). New must not overlap.
        if s_new < (e_old + turnover) and s_old < (e_new + turnover):
            raise err(ERR_ROOM_DOUBLE_BOOKED, "Booking overlaps an existing booking on the room")

    # OCC on Room.version (priority 21).
    if expected_room_version != room["version"]:
        raise err(ERR_STALE_VERSION, "expected_room_version does not match current room version")

    rec = {
        "episode_id": episode_id,
        "room_id": room_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "HELD",
    }
    stamp_new(rec)
    db.bookings[rec["id"]] = rec
    # Creating a booking advances the room's version by one.
    touch(room)
    return object_response(public(rec), 201)


@bp.route("/birth-center/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_booking(bid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/bookings", methods=["GET"])
def list_bookings():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    room_id = request.args.get("room_id")
    episode_id = request.args.get("episode_id")
    status = request.args.get("status")
    records = [r for r in db.bookings.values()
               if (room_id is None or r["room_id"] == room_id)
               and (episode_id is None or r["episode_id"] == episode_id)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_booking(bid)
    if rec["status"] != "HELD":
        raise err(ERR_INVALID_STATE, "Booking is not HELD")
    room = db.rooms.get(rec["room_id"])
    if room is None or room["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Room is not OPEN")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/birth-center/bookings/<bid>/check-in", methods=["POST"])
def check_in(bid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_booking(bid)
    if rec["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Booking is not CONFIRMED")
    episode = db.episodes.get(rec["episode_id"])
    if episode is None or episode["clinical_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Episode is not ACTIVE")
    if db.logical_clock < parse_dt(rec["starts_at"], "starts_at"):
        raise err(ERR_INVALID_STATE, "Logical clock has not reached starts_at")
    rec["status"] = "IN_USE"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/birth-center/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_booking(bid)
    if rec["status"] not in ("HELD", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Booking cannot be cancelled from this state")
    rec["status"] = "CANCELLED"
    touch(rec)
    # room interval released; advances the room's version by one.
    room = db.rooms.get(rec["room_id"])
    if room is not None:
        touch(room)
    return object_response(public(rec), 200)
