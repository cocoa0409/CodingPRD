"""Room routes."""
from flask import Blueprint, request

from db import rooms, room_types, maintenance_blocks, stamp_create, stamp_update, lock
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.projections import project_room
from services.validation import require_dict, required_str
from services.listing import list_resource

bp = Blueprint("rooms", __name__)


_LIST_ROLES = ["PlatformAdmin", "FrontDeskClerk", "HousekeepingStaff",
               "RevenueAnalyst", "RevenueManager"]


@bp.route("/hotel/rooms", methods=["POST"])
@require_auth(roles=["PlatformAdmin"])
def create_room():
    body = require_dict(request.get_json(silent=True))
    room_number = required_str(body, "room_number")
    room_type_id = required_str(body, "room_type_id")

    with lock():
        rt = room_types.get(room_type_id)
        if rt is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType not found")
        if rt.get("status") != "ACTIVE":
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType is not ACTIVE")
        # uniqueness across rooms with lifecycle_status == ACTIVE
        for r in rooms.values():
            if r.get("lifecycle_status") == "ACTIVE" and r.get("room_number") == room_number:
                raise err("ERR_INVALID_INPUT", "room_number already in use among active rooms")

        row = {
            "room_number": room_number,
            "room_type_id": room_type_id,
            "housekeeping_status": "VACANT_CLEAN",
            "operational_status": "IN_SERVICE",
            "lifecycle_status": "ACTIVE",
            "current_reservation_id": None,
        }
        stamp_create(row, common_fields=True)
        rooms[row["id"]] = row
    return success(project_room(row), 201)


@bp.route("/hotel/rooms", methods=["GET"])
@require_auth(roles=_LIST_ROLES)
def list_rooms():
    limit, offset = get_pagination()
    filters = {}
    for k in ("room_type_id", "housekeeping_status", "operational_status", "lifecycle_status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    items, total = list_resource(rooms, filters=filters,
                                  projector=project_room,
                                  limit=limit, offset=offset)
    return success_list(items, limit, offset, total)


@bp.route("/hotel/rooms/<rid>/clean", methods=["POST"])
@require_auth(roles=["HousekeepingStaff"])
def clean_room(rid):
    with lock():
        r = rooms.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Room not found")
        if r.get("housekeeping_status") != "DIRTY":
            raise err("ERR_INVALID_STATE", "Room is not DIRTY")
        if r.get("operational_status") != "IN_SERVICE":
            raise err("ERR_INVALID_STATE", "Room must be IN_SERVICE to clean")
        r["housekeeping_status"] = "VACANT_CLEAN"
        stamp_update(r)
    return success(project_room(r))


@bp.route("/hotel/rooms/<rid>/out-of-service", methods=["POST"])
@require_auth(roles=["HousekeepingStaff"])
def out_of_service_room(rid):
    with lock():
        r = rooms.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Room not found")
        if r.get("operational_status") != "IN_SERVICE":
            raise err("ERR_INVALID_STATE", "Room is not IN_SERVICE")
        if r.get("housekeeping_status") == "OCCUPIED":
            raise err("ERR_INVALID_STATE", "Room is currently OCCUPIED")
        r["operational_status"] = "OUT_OF_ORDER"
        stamp_update(r)
        # Cascade: any SCHEDULED block with start <= today < end transitions to ACTIVE
        from clock import today_utc, parse_date
        today = today_utc()
        for b in maintenance_blocks.values():
            if b.get("room_id") != rid:
                continue
            if b.get("status") != "SCHEDULED":
                continue
            sd = parse_date(b["start_date"])
            ed = parse_date(b["end_date"])
            if sd <= today < ed:
                b["status"] = "ACTIVE"
                stamp_update(b)
    return success(project_room(r))


@bp.route("/hotel/rooms/<rid>/return-to-service", methods=["POST"])
@require_auth(roles=["HousekeepingStaff"])
def return_to_service_room(rid):
    with lock():
        r = rooms.get(rid)
        if r is None:
            raise err("ERR_NOT_FOUND", "Room not found")
        if r.get("operational_status") != "OUT_OF_ORDER":
            raise err("ERR_INVALID_STATE", "Room is not OUT_OF_ORDER")
        # No MaintenanceBlock with status == ACTIVE for this room
        for b in maintenance_blocks.values():
            if b.get("room_id") == rid and b.get("status") == "ACTIVE":
                raise err("ERR_INVALID_STATE", "Room has an ACTIVE maintenance block")
        r["operational_status"] = "IN_SERVICE"
        stamp_update(r)
    return success(project_room(r))
