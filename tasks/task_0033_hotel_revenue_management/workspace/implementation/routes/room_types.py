"""RoomType routes."""
from flask import Blueprint, request

from db import room_types, stamp_create, lock
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.projections import project_room_type
from services.validation import (
    require_dict, required_str, required_int, in_range, must_uppercase, length_in
)
from services.listing import list_resource


bp = Blueprint("room_types", __name__)


_ALL_AUTH = ["PlatformAdmin", "RevenueAnalyst", "RevenueManager",
             "ReservationsAgent", "FrontDeskClerk", "HousekeepingStaff"]


@bp.route("/hotel/room-types", methods=["POST"])
@require_auth(roles=["PlatformAdmin"])
def create_room_type():
    body = require_dict(request.get_json(silent=True))
    code = required_str(body, "code")
    must_uppercase(code, "code")
    length_in(code, 2, 8, "code")
    name = required_str(body, "name")
    base_rate = required_int(body, "base_rate_cents")
    if base_rate < 1000:
        raise err("ERR_INVALID_INPUT", "base_rate_cents must be >= 1000")
    max_occ = required_int(body, "max_occupancy")
    in_range(max_occ, 1, 10, "max_occupancy")

    with lock():
        # uniqueness across non-retired room types
        for rt in room_types.values():
            if rt["code"] == code and rt.get("status") != "RETIRED":
                raise err("ERR_INVALID_INPUT", "code already in use among active room types")
        row = {
            "code": code,
            "name": name,
            "base_rate_cents": base_rate,
            "max_occupancy": max_occ,
            "status": "ACTIVE",
        }
        stamp_create(row, common_fields=True)
        room_types[row["id"]] = row
    return success(project_room_type(row), 201)


@bp.route("/hotel/room-types", methods=["GET"])
@require_auth(roles=_ALL_AUTH)
def list_room_types():
    limit, offset = get_pagination()
    status = request.args.get("status")
    filters = {}
    if status:
        filters["status"] = status
    items, total = list_resource(room_types, filters=filters,
                                  projector=project_room_type,
                                  limit=limit, offset=offset)
    return success_list(items, limit, offset, total)


@bp.route("/hotel/room-types/<rt_id>", methods=["GET"])
@require_auth(roles=_ALL_AUTH)
def get_room_type(rt_id):
    rt = room_types.get(rt_id)
    if rt is None:
        raise err("ERR_NOT_FOUND", "RoomType not found")
    return success(project_room_type(rt))
