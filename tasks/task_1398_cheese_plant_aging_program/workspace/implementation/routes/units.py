"""Aging unit resources: placement (OCC on room), turns, moves, removal
(PRD 3.6)."""

from flask import request

from db import STORES, new_record, now, touch
from errors import ApiError, invalid_request, invalid_state, stale_version
from helpers import auth, body, f_int, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp
from services import refresh_room_posture, unit_age_days, unit_turns_due

bp = make_bp("aging_units")

GET_ROLES = ("PlantAdmin", "AgingRoomOperator", "QAGrader")


def serialize_unit(rec):
    """The age/turn projection is recomputed whenever an IN_ROOM unit is read
    (PRD 2.4), so reported ages always reflect the current logical time."""
    out = serialize(rec)
    if rec["status"] == "IN_ROOM":
        out["age_days"] = unit_age_days(rec)
        out["turns_due"] = unit_turns_due(rec)
    return out


def _room_placement_gates(room, wheel_count):
    """Room gates for an incoming placement of wheel_count wheels."""
    if room["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ROOM_DECOMMISSIONED", 409, "Target room is DECOMMISSIONED")
    if room["posture"] == "DEVIATION":
        raise ApiError("ERR_ROOM_DEVIATION", 409, "Room posture DEVIATION blocks placement")
    if room["wheels_present"] + wheel_count > room["capacity_wheels"]:
        raise ApiError("ERR_ROOM_FULL", 409, "Placement would exceed room capacity")


@bp.post("/plant/aging-units")
def create_unit():
    auth("AgingRoomOperator")
    b = body()
    cheese_batch_id = f_str(b, "cheese_batch_id")
    aging_room_id = f_str(b, "aging_room_id")
    wheel_count = f_int(b, "wheel_count", positive=True)
    expected_room_version = f_int(b, "expected_aging_room_version")
    # Existence, body references in order (404).
    batch = get_or_404("cheese_batches", cheese_batch_id, "cheese batch")
    room = get_or_404("aging_rooms", aging_room_id, "aging room")
    # OCC on the room (412) before placement rules run.
    if expected_room_version != room["version"]:
        stale_version(
            "expected_aging_room_version does not match the room's current version"
        )
    # Rung 9 before rung 11 (PRD 2.9): wheels remaining, then room gates.
    if wheel_count > batch["wheels_produced"] - batch["wheels_placed"]:
        raise ApiError(
            "ERR_WHEELS_EXHAUSTED", 409, "wheel_count exceeds wheels not yet placed"
        )
    _room_placement_gates(room, wheel_count)
    # --- effects ---
    current = now()
    rec = new_record()
    rec.update(
        plant_id=batch["plant_id"],
        cheese_batch_id=batch["id"],
        aging_room_id=room["id"],
        wheel_count=wheel_count,
        entered_at=current,
        _entered_dt=current,
        age_days=0,
        last_turned_at=current,
        _last_turned_dt=current,
        turns_due=False,
        status="IN_ROOM",
    )
    STORES["aging_units"][rec["id"]] = rec
    batch["wheels_placed"] += wheel_count
    if batch["status"] == "GREEN":
        batch["status"] = "AGING"
    touch(batch)
    room["wheels_present"] += wheel_count
    refresh_room_posture(room)
    touch(room)
    return success(serialize_unit(rec), 201)


@bp.get("/plant/aging-units/<agingUnitId>")
def get_unit(agingUnitId):
    auth(*GET_ROLES)
    rec = get_or_404("aging_units", agingUnitId, "aging unit")
    return success(serialize_unit(rec))


@bp.get("/plant/aging-units")
def list_units():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "aging_units",
        [
            ("plant_id", request.args.get("plant_id")),
            ("cheese_batch_id", request.args.get("cheese_batch_id")),
            ("aging_room_id", request.args.get("aging_room_id")),
            ("status", request.args.get("status")),
            ("turns_due", request.args.get("turns_due")),
        ],
        serialize_unit,
    )
    return success(data, 200, pagination)


@bp.post("/plant/aging-units/<agingUnitId>/turn")
def turn_unit(agingUnitId):
    auth("AgingRoomOperator")
    body(required=False)
    rec = get_or_404("aging_units", agingUnitId, "aging unit")
    if rec["status"] != "IN_ROOM":
        invalid_state("Aging unit is not IN_ROOM")
    current = now()
    rec["last_turned_at"] = current
    rec["_last_turned_dt"] = current
    rec["turns_due"] = unit_turns_due(rec)
    touch(rec)
    return success(serialize_unit(rec))


@bp.post("/plant/aging-units/<agingUnitId>/move")
def move_unit(agingUnitId):
    auth("AgingRoomOperator")
    b = body()
    destination_id = f_str(b, "destination_aging_room_id")
    rec = get_or_404("aging_units", agingUnitId, "aging unit")
    dest = get_or_404("aging_rooms", destination_id, "aging room")
    if rec["status"] != "IN_ROOM":
        invalid_state("Aging unit is not IN_ROOM")
    if destination_id == rec["aging_room_id"]:
        invalid_request("Destination room must differ from the unit's current room")
    _room_placement_gates(dest, rec["wheel_count"])
    source = STORES["aging_rooms"].get(rec["aging_room_id"])
    if source is not None:
        source["wheels_present"] -= rec["wheel_count"]
        refresh_room_posture(source)
        touch(source)
    dest["wheels_present"] += rec["wheel_count"]
    refresh_room_posture(dest)
    touch(dest)
    # IN_ROOM -> MOVED -> IN_ROOM commits and immediately re-enters:
    # aging_room_id updated, entered_at (and thus the unit's age) preserved.
    rec["aging_room_id"] = dest["id"]
    rec["status"] = "IN_ROOM"
    touch(rec)
    return success(serialize_unit(rec))


@bp.post("/plant/aging-units/<agingUnitId>/remove")
def remove_unit(agingUnitId):
    auth("AgingRoomOperator")
    body(required=False)
    rec = get_or_404("aging_units", agingUnitId, "aging unit")
    if rec["status"] != "IN_ROOM":
        invalid_state("Aging unit is not IN_ROOM")
    batch = STORES["cheese_batches"].get(rec["cheese_batch_id"])
    if batch is None or batch["status"] not in ("RELEASED", "CONDEMNED"):
        invalid_state(
            "Wheels may leave aging only for allocation (RELEASED) or destruction (CONDEMNED)"
        )
    rec["status"] = "REMOVED"
    touch(rec)
    room = STORES["aging_rooms"].get(rec["aging_room_id"])
    if room is not None:
        room["wheels_present"] -= rec["wheel_count"]
        refresh_room_posture(room)
        touch(room)
    return success(serialize_unit(rec))
