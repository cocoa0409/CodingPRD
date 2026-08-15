"""OR room + SterilizerUnit routes."""

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, opt_int, req_int
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("rooms_units", __name__)


# ---------------------------------------------------------------------------
# OR Rooms
# ---------------------------------------------------------------------------

@bp.post("/or-rooms")
def create_room():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["ORScheduler"])

    room_name = req_str(body, "room_name")
    turnover_buffer_minutes = opt_int(body, "turnover_buffer_minutes", default=30, min_value=0)

    room = {
        "room_name": room_name,
        "turnover_buffer_minutes": turnover_buffer_minutes,
    }
    core.stamp_new(room)
    db.or_rooms[room["id"]] = room
    return success_object(core.serialize(room), status=201)


@bp.get("/or-rooms")
def list_rooms():
    get_auth()
    items = sorted(db.or_rooms.values(), key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(r) for r in page], limit, offset, total)


@bp.get("/or-rooms/<id>")
def get_room(id):
    get_auth()
    room = db.or_rooms.get(id)
    if room is None:
        raise_err("ERR_ROOM_NOT_FOUND", "OR room not found")
    return success_object(core.serialize(room))


# ---------------------------------------------------------------------------
# Sterilizer Units
# ---------------------------------------------------------------------------

@bp.post("/sterilizer-units")
def create_unit():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["SterileProcessingTech"])

    unit_name = req_str(body, "unit_name")
    slot_capacity = req_int(body, "slot_capacity", min_value=1)
    cycle_minutes = req_int(body, "cycle_minutes", min_value=1)
    cooldown_minutes = req_int(body, "cooldown_minutes", min_value=0)

    unit = {
        "unit_name": unit_name,
        "slot_capacity": slot_capacity,
        "cycle_minutes": cycle_minutes,
        "cooldown_minutes": cooldown_minutes,
    }
    core.stamp_new(unit)
    db.sterilizer_units[unit["id"]] = unit
    return success_object(core.serialize(unit), status=201)


@bp.get("/sterilizer-units")
def list_units():
    get_auth()
    items = sorted(db.sterilizer_units.values(), key=lambda u: u["_seq"])
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(u) for u in page], limit, offset, total)


@bp.get("/sterilizer-units/<id>")
def get_unit(id):
    get_auth()
    unit = db.sterilizer_units.get(id)
    if unit is None:
        raise_err("ERR_STERILIZER_NOT_FOUND", "Sterilizer unit not found")
    return success_object(core.serialize(unit))
