"""Studio, Room, Bike, Instructor endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint

from constants import (
    ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR,
    DEFAULT_TIMEZONE, DEFAULT_LATE_CANCEL_WINDOW_MINUTES,
    DEFAULT_LATE_CANCEL_FEE_CENTS, DEFAULT_NO_SHOW_FEE_CENTS,
)
from db import db, stamp_new, touch
from errors import err, ERR_VALIDATION, ERR_INVALID_STATE
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import studio_out, room_out, bike_out, instructor_out
from services import lookup, validate, paging

bp = Blueprint("facilities", __name__)

READ_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR}


# ---- Studio ----
@bp.route("/studios", methods=["POST"])
def create_studio():
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    body = validate.get_body()
    name = validate.require_str(body, "name")
    city = validate.require_str(body, "city")
    timezone = validate.opt_str(body, "timezone", DEFAULT_TIMEZONE)
    lcw = validate.opt_int(body, "late_cancel_window_minutes", DEFAULT_LATE_CANCEL_WINDOW_MINUTES, minimum=0)
    lcf = validate.opt_int(body, "late_cancel_fee_cents", DEFAULT_LATE_CANCEL_FEE_CENTS, minimum=0)
    nsf = validate.opt_int(body, "no_show_fee_cents", DEFAULT_NO_SHOW_FEE_CENTS, minimum=0)
    rec = {
        "name": name, "city": city, "timezone": timezone,
        "late_cancel_window_minutes": lcw,
        "late_cancel_fee_cents": lcf,
        "no_show_fee_cents": nsf,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.studios[rec["id"]] = rec
    return success_object(studio_out(rec), 201)


@bp.route("/studios/<studio_id>", methods=["GET"])
def get_studio(studio_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_studio(studio_id)
    return success_object(studio_out(rec), 200)


@bp.route("/studios", methods=["GET"])
def list_studios():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = paging.get_pagination()
    records = paging.sort_default(list(db.studios.values()))
    page, total = paging.apply_page(records, limit, offset)
    return success_array([studio_out(r) for r in page], limit, offset, total)


# ---- Room ----
@bp.route("/studios/<studio_id>/rooms", methods=["POST"])
def create_room(studio_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    lookup.get_studio(studio_id)
    body = validate.get_body()
    name = validate.require_str(body, "name")
    rec = {"studio_id": studio_id, "name": name, "status": "OPEN"}
    stamp_new(rec)
    db.rooms[rec["id"]] = rec
    return success_object(room_out(rec), 201)


@bp.route("/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_room(room_id)
    return success_object(room_out(rec), 200)


@bp.route("/studios/<studio_id>/rooms", methods=["GET"])
def list_rooms(studio_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    lookup.get_studio(studio_id)
    limit, offset = paging.get_pagination()
    records = [r for r in db.rooms.values() if r["studio_id"] == studio_id]
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([room_out(r) for r in page], limit, offset, total)


# ---- Bike ----
@bp.route("/studios/<studio_id>/rooms/<room_id>/bikes", methods=["POST"])
def create_bike(studio_id, room_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    room = lookup.get_room_in_studio(studio_id, room_id)
    body = validate.get_body()
    position_row = validate.require_int(body, "position_row", minimum=1)
    position_col = validate.require_int(body, "position_col", minimum=1)
    label = validate.require_str(body, "label")
    rec = {
        "room_id": room_id,
        "position_row": position_row,
        "position_col": position_col,
        "label": label,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.bikes[rec["id"]] = rec
    # Recompute parent room.bike_count (derived) -> mutation of the room.
    touch(room)
    return success_object(bike_out(rec), 201)


@bp.route("/rooms/<room_id>/bikes", methods=["GET"])
def list_bikes(room_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    lookup.get_room(room_id)
    limit, offset = paging.get_pagination()
    records = [b for b in db.bikes.values() if b["room_id"] == room_id]
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([bike_out(b) for b in page], limit, offset, total)


@bp.route("/studios/<studio_id>/rooms/<room_id>/bikes/<bike_id>/retire", methods=["POST"])
def retire_bike(studio_id, room_id, bike_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    room = lookup.get_room_in_studio(studio_id, room_id)
    bike = lookup.get_bike_in_room(studio_id, room_id, bike_id)
    if bike["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Bike is not ACTIVE")
    bike["status"] = "RETIRED"
    touch(bike)
    touch(room)  # recompute room.bike_count
    return success_object(bike_out(bike), 200)


# ---- Instructor ----
@bp.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    body = validate.get_body()
    email = validate.require_str(body, "email")
    full_name = validate.require_str(body, "full_name")
    rec = {"email": email, "full_name": full_name, "status": "ACTIVE"}
    stamp_new(rec)
    db.instructors[rec["id"]] = rec
    return success_object(instructor_out(rec), 201)
