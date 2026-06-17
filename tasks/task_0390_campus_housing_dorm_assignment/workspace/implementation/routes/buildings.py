"""Buildings & Rooms (inventory) routes."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("buildings", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
BUILDING_TYPES = {"TRADITIONAL", "SUITE", "APARTMENT"}
ROOM_TYPES = {"SINGLE", "DOUBLE", "TRIPLE", "SUITE_DOUBLE"}
GENDER_INCLUSIVITY = {"SINGLE_GENDER", "ALL_GENDER"}


# --------------------------------------------------------------------------
# Buildings
# --------------------------------------------------------------------------
@bp.route("/buildings", methods=["POST"])
def create_building():
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    body = common.get_body()

    common.require_fields(body, ["name", "building_type"])
    name = body["name"]
    building_type = common.require_enum(body, "building_type", BUILDING_TYPES)

    offers_break = body.get("offers_break_housing", False)
    if offers_break is None:
        offers_break = False
    if not isinstance(offers_break, bool):
        raise errors.invalid_request("offers_break_housing must be a boolean.")

    capacity = common.optional_int(body, "break_housing_capacity", default=0, min_value=0)

    with db.LOCK:
        rec = core.init_record({
            "name": name,
            "building_type": building_type,
            "offers_break_housing": offers_break,
            "break_housing_capacity": capacity,
            "total_bed_count": 0,
            "occupied_bed_count": 0,
        })
        db.buildings[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/buildings/<building_id>", methods=["GET"])
def get_building(building_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.buildings, building_id)
        return response.object_response(core.serialize(rec))


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------
@bp.route("/buildings/<building_id>/rooms", methods=["POST"])
def create_room(building_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        building = core.get_or_404(db.buildings, building_id)
        body = common.get_body()

        common.require_fields(body, ["room_number", "room_type", "gender_inclusivity"])
        room_number = body["room_number"]
        room_type = common.require_enum(body, "room_type", ROOM_TYPES)
        gender_inclusivity = common.require_enum(body, "gender_inclusivity", GENDER_INCLUSIVITY)

        rate = common.optional_int(body, "nightly_break_rate_cents", default=4500, min_value=0)

        rec = core.init_record({
            "building_id": building["id"],
            "room_number": room_number,
            "room_type": room_type,
            "bed_capacity": core.ROOM_BED_CAPACITY[room_type],
            "gender_inclusivity": gender_inclusivity,
            "nightly_break_rate_cents": rate,
            "occupied_bed_count": 0,
            "open_incident_count": 0,
            "status": "OPEN",
        })
        db.rooms[rec["id"]] = rec
        core.reconcile_building(building)
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/buildings/<building_id>/rooms", methods=["GET"])
def list_building_rooms(building_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        core.get_or_404(db.buildings, building_id)
        limit, offset = common.parse_pagination()
        items = [r for r in db.rooms.values() if r["building_id"] == building_id]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(r) for r in page], limit, offset, total
        )


@bp.route("/rooms", methods=["GET"])
def list_rooms():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        building_id = request.args.get("building_id")
        items = list(db.rooms.values())
        if building_id is not None:
            items = [r for r in items if r["building_id"] == building_id]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(r) for r in page], limit, offset, total
        )


@bp.route("/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.rooms, room_id)
        return response.object_response(core.serialize(rec))


@bp.route("/rooms/<room_id>/take-offline", methods=["POST"])
def take_offline(room_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        room = core.get_or_404(db.rooms, room_id)
        body = common.get_body()
        # Business: blocked while occupied (priority 16) before OCC (priority 18).
        if room["status"] == "OFFLINE":
            raise errors.invalid_state("Room is already OFFLINE.")
        if room["occupied_bed_count"] > 0:
            raise errors.room_occupied()
        _check_room_version(room, body)
        room["status"] = "OFFLINE"
        core.touch(room)
        core.reconcile_building_for_room(room)
        return response.object_response(core.serialize(room))


@bp.route("/rooms/<room_id>/restore", methods=["POST"])
def restore(room_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        room = core.get_or_404(db.rooms, room_id)
        body = common.get_body()
        if room["status"] != "OFFLINE":
            raise errors.invalid_state("Room is not OFFLINE.")
        _check_room_version(room, body)
        # Re-derive posture from current occupancy/incidents.
        room["status"] = "OPEN"  # provisional; derive_room_status recomputes
        room["occupied_bed_count"] = core.room_occupied_count(room["id"])
        room["open_incident_count"] = core.room_open_incident_count(room["id"])
        room["status"] = core.derive_room_status(room)
        core.touch(room)
        core.reconcile_building_for_room(room)
        return response.object_response(core.serialize(room))


def _check_room_version(room, body):
    common.require_fields(body, ["expected_room_version"])
    expected = body["expected_room_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_room_version must be an integer.")
    if expected != room["version"]:
        raise errors.stale_version("expected_room_version does not match.")
