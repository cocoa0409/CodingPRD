"""Aging room resources (PRD 3.1)."""

from flask import request

from db import STORES, new_record, touch
from errors import ApiError, invalid_request, invalid_state
from helpers import auth, body, f_int, f_num, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp
from services import refresh_room_posture

bp = make_bp("aging_rooms")

GET_ROLES = ("PlantAdmin", "AgingRoomOperator", "QAGrader")


@bp.post("/plant/plants/<plantId>/aging-rooms")
def create_room(plantId):
    auth("PlantAdmin")
    b = body()
    code = f_str(b, "code")
    capacity_wheels = f_int(b, "capacity_wheels", positive=True)
    temp_c = f_num(b, "temp_c")
    humidity_pct = f_num(b, "humidity_pct")
    plant = get_or_404("plants", plantId, "plant")
    for r in STORES["aging_rooms"].values():
        if r["plant_id"] == plant["id"] and r["code"] == code:
            invalid_request(f"Room code '{code}' already exists for this plant")
    rec = new_record()
    rec.update(
        plant_id=plant["id"],
        code=code,
        capacity_wheels=capacity_wheels,
        wheels_present=0,
        temp_c=temp_c,
        humidity_pct=humidity_pct,
        posture="AVAILABLE",
        status="ACTIVE",
    )
    refresh_room_posture(rec)
    STORES["aging_rooms"][rec["id"]] = rec
    # Capacity ledger: the plant's total aging capacity rises in the same op.
    plant["total_aging_capacity_wheels"] += capacity_wheels
    touch(plant)
    return success(serialize(rec), 201)


@bp.get("/plant/aging-rooms/<agingRoomId>")
def get_room(agingRoomId):
    auth(*GET_ROLES)
    rec = get_or_404("aging_rooms", agingRoomId, "aging room")
    return success(serialize(rec))


@bp.get("/plant/aging-rooms")
def list_rooms():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "aging_rooms",
        [
            ("plant_id", request.args.get("plant_id")),
            ("status", request.args.get("status")),
            ("posture", request.args.get("posture")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.patch("/plant/aging-rooms/<agingRoomId>")
def update_room(agingRoomId):
    auth("AgingRoomOperator")
    b = body(required=False)
    rec = get_or_404("aging_rooms", agingRoomId, "aging room")
    temp_c = f_num(b, "temp_c", required=False)
    humidity_pct = f_num(b, "humidity_pct", required=False)
    if temp_c is not None:
        rec["temp_c"] = temp_c
    if humidity_pct is not None:
        rec["humidity_pct"] = humidity_pct
    # Posture re-derived (DEVIATION check precedes FULL); a DECOMMISSIONED
    # room's posture is frozen and never re-derived.
    refresh_room_posture(rec)
    touch(rec)
    return success(serialize(rec))


@bp.post("/plant/aging-rooms/<agingRoomId>/decommission")
def decommission_room(agingRoomId):
    auth("PlantAdmin")
    body(required=False)
    rec = get_or_404("aging_rooms", agingRoomId, "aging room")
    if rec["status"] != "ACTIVE":
        invalid_state("Aging room is not ACTIVE")
    if rec["wheels_present"] > 0:
        raise ApiError("ERR_ROOM_NOT_EMPTY", 409, "Decommission attempted with wheels present")
    rec["status"] = "DECOMMISSIONED"  # posture freezes from here on
    touch(rec)
    plant = STORES["plants"].get(rec["plant_id"])
    if plant is not None:
        plant["total_aging_capacity_wheels"] -= rec["capacity_wheels"]
        touch(plant)
    return success(serialize(rec))
