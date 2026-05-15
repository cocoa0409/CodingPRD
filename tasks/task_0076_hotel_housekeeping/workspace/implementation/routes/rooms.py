"""Routes for /rooms."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ROOM_NOT_FOUND,
    ERR_MANUAL_CORRECTION_INVALID_TARGET,
)
from middleware import auth_required
from response import success_response, list_response
from services.audit import append_room_status_event
from services.calculations import recompute_discrepancy
from services.common import (
    bump,
    check_version,
    require_body_dict,
    require_enum,
    require_field,
    stamp_create,
)
from services.pagination import parse_pagination, paginate
from services.serializers import serialize_room, serialize_room_status_event
from services.room_machine import (
    ALL_NON_OUT_OF_ORDER,
    transition_room,
)
from services.time_util import now_utc, parse_iso


bp = Blueprint("rooms", __name__)


ROOM_TYPES = {"STANDARD", "SUITE", "PRESIDENTIAL"}
PMS_OCCUPANCIES = {"VACANT", "OCCUPIED", "DUE_OUT", "NO_SHOW"}
ROOM_STATUSES = {
    "VACANT_CLEAN", "VACANT_DIRTY",
    "OCCUPIED_CLEAN", "OCCUPIED_DIRTY",
    "INSPECTED", "OUT_OF_ORDER",
}


def get_room_or_404(room_id):
    room = DB["rooms"].get(room_id)
    if room is None:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
    return room


@bp.route("/rooms", methods=["POST"])
@auth_required(["FrontDesk"])
def create_room():
    body = require_body_dict(request.get_json(silent=True))
    room_number = require_field(body, "room_number", str)
    zone_code = require_field(body, "zone_code", str)
    room_type = require_enum(body, "room_type", ROOM_TYPES)
    vip_flag = body.get("vip_flag", False)
    pms_occupancy = body.get("pms_occupancy", "VACANT")

    if pms_occupancy is None:
        pms_occupancy = "VACANT"
    if pms_occupancy not in PMS_OCCUPANCIES:
        raise_error(ERR_INVALID_REQUEST,
                    "pms_occupancy must be one of VACANT|OCCUPIED|DUE_OUT|NO_SHOW")
    if not isinstance(vip_flag, bool):
        raise_error(ERR_INVALID_REQUEST, "vip_flag must be boolean")
    if not room_number:
        raise_error(ERR_INVALID_REQUEST, "room_number must be non-empty")

    with LOCK:
        # Uniqueness on room_number
        for r in DB["rooms"].values():
            if r["room_number"] == room_number:
                raise_error(ERR_INVALID_REQUEST,
                            "room_number must be unique")

        status = "OCCUPIED_DIRTY" if pms_occupancy == "OCCUPIED" else "VACANT_CLEAN"
        room = {
            "room_number": room_number,
            "zone_code": zone_code,
            "room_type": room_type,
            "vip_flag": bool(vip_flag),
            "pms_occupancy": pms_occupancy,
            "pms_synced_at": None,
            "status": status,
            "discrepancy_flag": False,
            "out_of_order_ticket_id": None,
            "last_cleaned_at": None,
            "_last_status_change_at": now_utc().isoformat(),
        }
        stamp_create(room)
        DB["rooms"][room["id"]] = room
        # Initial RoomStatusEvent
        append_room_status_event(
            room_id=room["id"],
            previous_status=None,
            new_status=status,
            change_reason="INITIAL",
            actor_id=g.user_id,
            correction_note=None,
        )
        recompute_discrepancy(room, audit_on_flip=True)

    return success_response(serialize_room(room), http_status=201)


@bp.route("/rooms", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def list_rooms():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    zone_filter = request.args.get("zone")
    discrepancy_only = request.args.get("discrepancy_only")

    items = list(DB["rooms"].values())
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    if zone_filter:
        items = [r for r in items if r["zone_code"] == zone_filter]
    if discrepancy_only is not None:
        truthy = str(discrepancy_only).lower() in {"true", "1", "yes"}
        if truthy:
            items = [r for r in items if r.get("discrepancy_flag")]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response([serialize_room(r) for r in page], total, limit, offset)


@bp.route("/rooms/<room_id>", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def get_room(room_id):
    room = get_room_or_404(room_id)
    return success_response(serialize_room(room))


@bp.route("/rooms/<room_id>/correct-status", methods=["POST"])
@auth_required(["Supervisor"])
def correct_status(room_id):
    body = require_body_dict(request.get_json(silent=True))
    new_status = require_field(body, "new_status", str)
    correction_note = require_field(body, "correction_note", str)
    if new_status not in ROOM_STATUSES:
        raise_error(ERR_INVALID_REQUEST, "Invalid new_status")
    if not correction_note:
        raise_error(ERR_INVALID_REQUEST, "correction_note must be non-empty")

    with LOCK:
        room = get_room_or_404(room_id)
        # State validation
        if room["status"] == "OUT_OF_ORDER":
            raise_error(ERR_MANUAL_CORRECTION_INVALID_TARGET,
                        "Cannot exit OUT_OF_ORDER via manual correction")
        if new_status == "OUT_OF_ORDER":
            raise_error(ERR_MANUAL_CORRECTION_INVALID_TARGET,
                        "Cannot enter OUT_OF_ORDER via manual correction")
        if new_status == room["status"]:
            raise_error(ERR_MANUAL_CORRECTION_INVALID_TARGET,
                        "new_status equals current status")
        check_version(room, body)

        room["_last_actor"] = g.user_id
        transition_room(
            room,
            new_status,
            change_reason="MANUAL_CORRECTION",
            actor_id=g.user_id,
            correction_note=correction_note,
            write_audit=True,
        )
    return success_response(serialize_room(room))


@bp.route("/rooms/<room_id>/status-events", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def list_status_events(room_id):
    get_room_or_404(room_id)
    limit, offset = parse_pagination()
    items = [e for e in DB["room_status_events"].values() if e["room_id"] == room_id]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_room_status_event(e) for e in page], total, limit, offset
    )
