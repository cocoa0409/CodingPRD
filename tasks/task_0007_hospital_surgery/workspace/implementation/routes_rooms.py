from flask import Blueprint

from db import db
from errors import raise_error, ERR_ROOM_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import auth_required
from response import success, paginate
from serialize import serialize_room
from utils import get_json_body, require_str, require_number, get_pagination, optional_number

ROOM_TYPES = {"GENERAL_OR", "CARDIAC_OR", "NEURO_OR", "OBSTETRIC_OR"}
SPECIALTIES = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC"}

bp = Blueprint("rooms", __name__)


@bp.route("/operating-rooms", methods=["POST"])
@auth_required("Scheduler")
def create_room():
    body = get_json_body()
    room_number = require_str(body, "room_number")
    room_type = require_str(body, "room_type")
    if room_type not in ROOM_TYPES:
        raise_error(ERR_INVALID_REQUEST, f"room_type must be one of {sorted(ROOM_TYPES)}")
    equipment_list = body.get("equipment_list")
    if equipment_list is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required field 'equipment_list'")
    if not isinstance(equipment_list, list) or any(not isinstance(x, str) for x in equipment_list):
        raise_error(ERR_INVALID_REQUEST, "equipment_list must be a list of strings")
    specialty_required = require_str(body, "specialty_required")
    if specialty_required not in SPECIALTIES:
        raise_error(ERR_INVALID_REQUEST, f"specialty_required must be one of {sorted(SPECIALTIES)}")
    turnover_buffer = body.get("turnover_buffer_minutes", 30)
    if isinstance(turnover_buffer, bool) or not isinstance(turnover_buffer, int) or turnover_buffer < 0:
        raise_error(ERR_INVALID_REQUEST, "turnover_buffer_minutes must be a non-negative integer")
    hourly_rate = require_number(body, "hourly_rate")

    with db.lock:
        room = {
            "room_number": room_number,
            "room_type": room_type,
            "equipment_list": equipment_list,
            "specialty_required": specialty_required,
            "turnover_buffer_minutes": turnover_buffer,
            "hourly_rate": hourly_rate,
        }
        db.stamp_create(room)
        db.operating_rooms[room["id"]] = room
    return success(serialize_room(room), status_code=201)


@bp.route("/operating-rooms", methods=["GET"])
@auth_required("Any")
def list_rooms():
    limit, offset = get_pagination()
    with db.lock:
        items = sorted(db.operating_rooms.values(), key=lambda r: (r["created_at"], r["_seq"]))
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_room(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/operating-rooms/<room_id>", methods=["GET"])
@auth_required("Any")
def get_room(room_id):
    with db.lock:
        room = db.operating_rooms.get(room_id)
        if room is None:
            raise_error(ERR_ROOM_NOT_FOUND, f"OperatingRoom {room_id} not found")
        return success(serialize_room(room))
