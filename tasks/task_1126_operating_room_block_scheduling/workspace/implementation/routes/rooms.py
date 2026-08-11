"""OperatingRoom endpoints."""

from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_ROOM_NOT_FOUND
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import room_json
from services import new_common

bp = Blueprint("rooms", __name__)


@bp.route("/operating-rooms", methods=["POST"])
def create_room():
    require_roles("SchedulingAdmin")
    body = get_json_body()
    room_name = body.get("room_name")
    is_hybrid = body.get("is_hybrid", False)
    if not isinstance(room_name, str) or not room_name:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "room_name is required and must be a string"
        )
    if not isinstance(is_hybrid, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "is_hybrid must be a boolean")
    rec = new_common()
    rec.update({"room_name": room_name, "is_hybrid": is_hybrid})
    db.rooms[rec["id"]] = rec
    return success_object(room_json(rec), 201)


@bp.route("/operating-rooms", methods=["GET"])
def list_rooms():
    get_auth()
    items = [room_json(r) for r in db.rooms.values()]
    items.sort(key=lambda r: (r["created_at"],))
    return paginate(items)
