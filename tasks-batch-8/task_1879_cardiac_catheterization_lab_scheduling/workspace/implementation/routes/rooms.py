"""CathLabRoom endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_IN_USE,
    ERR_ROOM_NOT_FOUND,
)
from helpers import get_payload, new_id, opt_code_list, paginate, req_str
from middleware import ALL_ROLES, require_roles
from response import success
from services import new_entity, room_out, touch

bp = Blueprint("rooms", __name__)


@bp.route("/cath-lab/rooms", methods=["POST"])
@require_roles("CathLabScheduler")
def create_room():
    data = get_payload()
    room_name = req_str(data, "room_name")
    equipment_profile = opt_code_list(data, "equipment_profile")
    room = new_entity()
    room["id"] = new_id()
    room.update(
        {
            "room_name": room_name,
            "equipment_profile": equipment_profile,
            "status": "ACTIVE",
        }
    )
    STORE["rooms"][room["id"]] = room
    return success(room_out(room), 201)


@bp.route("/cath-lab/rooms", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_rooms():
    status = request.args.get("status")
    items = [
        r
        for r in STORE["rooms"].values()
        if status is None or r["status"] == status
    ]
    items.sort(key=lambda r: r["_seq"])
    page, pg = paginate(items)
    return success([room_out(r) for r in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/rooms/<room_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_room(room_id):
    room = STORE["rooms"].get(room_id)
    if room is None:
        raise ApiError(ERR_ROOM_NOT_FOUND, "No CathLabRoom with the given id", 404)
    return success(room_out(room), 200)


@bp.route("/cath-lab/rooms/<room_id>", methods=["PATCH"])
@require_roles("CathLabScheduler")
def patch_room(room_id):
    room = STORE["rooms"].get(room_id)
    if room is None:
        raise ApiError(ERR_ROOM_NOT_FOUND, "No CathLabRoom with the given id", 404)
    data = get_payload()
    status = req_str(data, "status")
    if status not in ("ACTIVE", "OUT_OF_SERVICE"):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "status must be ACTIVE or OUT_OF_SERVICE",
            400,
        )
    if status == room["status"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "status is already %s" % status,
            400,
        )
    if status == "OUT_OF_SERVICE":
        in_use = any(
            c["lab_id"] == room_id and c["status"] in ("SCHEDULED", "IN_PROGRESS")
            for c in STORE["cases"].values()
        )
        if in_use:
            raise ApiError(
                ERR_RESOURCE_IN_USE,
                "Room has SCHEDULED or IN_PROGRESS cases",
                409,
            )
    room["status"] = status
    touch(room)
    return success(room_out(room), 200)
