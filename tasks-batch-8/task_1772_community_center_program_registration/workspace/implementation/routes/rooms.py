"""Room endpoints (PRD 3.1)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    check_int_range,
    get_or_404,
    new_record,
    req_enum,
    req_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("rooms", __name__)

FIELDS = ["id", "name", "capacity", "status", "created_at", "updated_at", "version"]

ROOM_STATUSES = ["ACTIVE", "MAINTENANCE"]


def room_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/rooms", methods=["POST"])
def create_room():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    name = req_str(body, "name")
    capacity = req_int(body, "capacity")
    check_int_range(capacity, 1, None, "capacity")
    rec = new_record()
    rec.update(name=name, capacity=capacity, status="ACTIVE")
    store.rooms[rec["id"]] = rec
    return success_object(room_out(rec), 201)


@bp.route("/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.rooms, room_id, "Room")
    return success_object(room_out(rec), 200)


@bp.route("/rooms/<room_id>", methods=["PATCH"])
def patch_room(room_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    status = req_enum(body, "status", ROOM_STATUSES)
    rec = get_or_404(store.rooms, room_id, "Room")
    if rec["status"] == status:
        # Only ACTIVE <-> MAINTENANCE transitions are defined.
        raise_err("ERR_INVALID_STATE", "Room is already %s" % status)
    rec["status"] = status
    bump(rec)
    return success_object(room_out(rec), 200)
