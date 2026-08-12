"""Building season lifecycle (PRD 3.1) and room creation/listing."""
from flask import Blueprint

from authz import ADMIN, FACILITIES, ALL_ROLES, require_roles
from db import store
from errors import invalid_state
from respond import success
from serialize import ser_building, ser_room
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_int,
    req_str, req_temporal, sorted_by_creation, touch,
)

bp = Blueprint("buildings", __name__)

LIFECYCLE_ROLES = [FACILITIES, ADMIN]


@bp.route("/buildings", methods=["POST"])
def create_building():
    require_roles([ADMIN])
    data = json_body()
    name = req_str(data, "name")
    fall_opening_date = req_temporal(data, "fall_opening_date")
    key_pool_size = req_int(data, "key_pool_size", minimum=0)
    b = {
        "id": new_id(),
        "_seq": next(store.seq),
        "name": name,
        "fall_opening_date": fall_opening_date,
        "key_pool_size": key_pool_size,
        "status": "ACADEMIC_USE",
        "released_bed_count": 0,
        "reserved_bed_count": 0,
        "available_bed_count": 0,
        "scheduled_turn_count": 0,
        "out_of_service_room_count": 0,
        "available_key_count": 0,
    }
    b.update(new_common_fields())
    store.buildings[b["id"]] = b
    return success(ser_building(b), status=201)


@bp.route("/buildings", methods=["GET"])
def list_buildings():
    require_roles(ALL_ROLES)
    status = _status_filter()
    items = [b for b in store.buildings.values() if status is None or b["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_building(b) for b in page], response_type="array", pagination=pagination)


def _status_filter():
    from flask import request
    return request.args.get("status")


@bp.route("/buildings/<bid>", methods=["GET"])
def get_building(bid):
    require_roles(ALL_ROLES)
    return success(ser_building(get_or_404(store.buildings, bid)))


def _transition(bid, from_status, to_status, extra=None):
    require_roles(LIFECYCLE_ROLES)
    b = get_or_404(store.buildings, bid)
    if b["status"] != from_status:
        raise invalid_state("Building must be %s for this transition" % from_status)
    if extra is not None:
        extra(b)
    b["status"] = to_status
    touch(b)
    return success(ser_building(b))


@bp.route("/buildings/<bid>/initiate-release", methods=["POST"])
def initiate_release(bid):
    return _transition(bid, "ACADEMIC_USE", "RELEASE_REVIEW")


@bp.route("/buildings/<bid>/confirm-release", methods=["POST"])
def confirm_release(bid):
    require_roles(LIFECYCLE_ROLES)
    b = get_or_404(store.buildings, bid)
    if b["status"] != "RELEASE_REVIEW":
        raise invalid_state("Building must be RELEASE_REVIEW to confirm release")
    rooms = [r for r in store.rooms.values() if r["building_id"] == bid]
    if len(rooms) < 1:
        raise invalid_state("Building must have at least one room to confirm release")
    for r in rooms:
        if r["status"] == "ACADEMIC_OCCUPIED":
            r["status"] = "RELEASED"
            touch(r)
    b["released_bed_count"] = sum(r["bed_count"] for r in rooms)
    b["reserved_bed_count"] = sum(
        1 for a in store.assignments.values()
        if a["status"] in ("RESERVED", "CHECKED_IN")
        and store.rooms[a["room_id"]]["building_id"] == bid
    )
    b["available_bed_count"] = b["released_bed_count"] - b["reserved_bed_count"]
    b["available_key_count"] = b["key_pool_size"]
    b["status"] = "RELEASED"
    touch(b)
    return success(ser_building(b))


@bp.route("/buildings/<bid>/abort-release", methods=["POST"])
def abort_release(bid):
    return _transition(bid, "RELEASE_REVIEW", "ACADEMIC_USE")


@bp.route("/buildings/<bid>/begin-turn-season", methods=["POST"])
def begin_turn_season(bid):
    return _transition(bid, "RELEASED", "TURN_ACTIVE")


def _fall_prep_guard(b):
    for a in store.assignments.values():
        if a["status"] in ("RESERVED", "CHECKED_IN") and store.rooms[a["room_id"]]["building_id"] == b["id"]:
            raise invalid_state("Active stay assignments remain in the building")
    for t in store.turn_tasks.values():
        if t["status"] in ("SCHEDULED", "IN_PROGRESS", "READY_FOR_INSPECTION", "FAILED") \
                and store.rooms[t["room_id"]]["building_id"] == b["id"]:
            raise invalid_state("Open turn tasks remain in the building")


@bp.route("/buildings/<bid>/begin-fall-prep", methods=["POST"])
def begin_fall_prep(bid):
    return _transition(bid, "TURN_ACTIVE", "FALL_PREP", extra=_fall_prep_guard)


def _certify_guard(b):
    if b["out_of_service_room_count"] != 0:
        raise invalid_state("Rooms remain out of service")
    for w in store.maintenance_windows.values():
        if w["building_id"] == b["id"] and w["status"] in ("CONFIRMED", "IN_PROGRESS"):
            raise invalid_state("Open maintenance windows remain for the building")


@bp.route("/buildings/<bid>/certify-fall-ready", methods=["POST"])
def certify_fall_ready(bid):
    return _transition(bid, "FALL_PREP", "READY_FOR_FALL", extra=_certify_guard)


@bp.route("/buildings/<bid>/reopen-academic", methods=["POST"])
def reopen_academic(bid):
    require_roles(LIFECYCLE_ROLES)
    b = get_or_404(store.buildings, bid)
    if b["status"] != "READY_FOR_FALL":
        raise invalid_state("Building must be READY_FOR_FALL to reopen")
    for r in store.rooms.values():
        if r["building_id"] == bid and r["status"] in ("READY", "RELEASED"):
            r["status"] = "ACADEMIC_OCCUPIED"
            touch(r)
    b["released_bed_count"] = 0
    b["reserved_bed_count"] = 0
    b["available_bed_count"] = 0
    b["status"] = "ACADEMIC_USE"
    touch(b)
    return success(ser_building(b))


@bp.route("/buildings/<bid>/rooms", methods=["POST"])
def create_room(bid):
    require_roles(LIFECYCLE_ROLES)
    b = get_or_404(store.buildings, bid)
    data = json_body()
    room_number = req_str(data, "room_number")
    bed_count = req_int(data, "bed_count", minimum=1)
    from errors import invalid_request
    for r in store.rooms.values():
        if r["building_id"] == bid and r["room_number"] == room_number:
            raise invalid_request("room_number must be unique within the building")
    if b["status"] not in ("ACADEMIC_USE", "RELEASE_REVIEW"):
        raise invalid_state("Rooms may be created only while the building is ACADEMIC_USE or RELEASE_REVIEW")
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "building_id": bid,
        "room_number": room_number,
        "bed_count": bed_count,
        "status": "ACADEMIC_OCCUPIED",
        "active_turn_task_id": None,
        "out_of_service_window_id": None,
    }
    r.update(new_common_fields())
    store.rooms[r["id"]] = r
    return success(ser_room(r), status=201)


@bp.route("/buildings/<bid>/rooms", methods=["GET"])
def list_rooms(bid):
    require_roles(ALL_ROLES)
    get_or_404(store.buildings, bid)
    status = _status_filter()
    items = [r for r in store.rooms.values()
             if r["building_id"] == bid and (status is None or r["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_room(r) for r in page], response_type="array", pagination=pagination)
