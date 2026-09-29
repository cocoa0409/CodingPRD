"""Break housing requests, decisions and occupancy."""
from flask import Blueprint, g

import calc
import derive
import responses
import services
import store
import validators as V
from auth import endpoint
from constants import API_PREFIX, BREAK_CODES, MAX_BREAK_SPAN_DAYS
from errors import ApiError
from store import DB

DIRECTOR = ["ResidenceDirector"]
RA_OR_DIRECTOR = ["ResidentAssistant", "ResidenceDirector"]
bp = Blueprint("breaks", __name__)


@bp.route("%s/break-housing-requests" % API_PREFIX, methods=["POST"])
@endpoint(["Student", "ResidenceDirector"])
def create_request():
    body = V.body()
    student_id = V.s_id(body, "student_id")
    room_id = V.s_id(body, "room_id")
    break_code = V.s_enum(body, "break_code", BREAK_CODES)
    start_date = V.s_date(body, "start_date")
    end_date = V.s_date(body, "end_date")
    reason = V.s_str(body, "reason")
    if end_date < start_date:
        raise ApiError("ERR_INVALID_REQUEST", "end_date must be on or after start_date.")
    if (end_date - start_date).days > MAX_BREAK_SPAN_DAYS:
        raise ApiError("ERR_INVALID_REQUEST", "A break stay may not span more than 45 days.")
    if store.get("students", student_id) is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    if store.get("rooms", room_id) is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    row = store.insert("breaks", "BreakHousingRequest", {
        "student_id": student_id,
        "room_id": room_id,
        "break_code": break_code,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "reason": reason,
        "status": "REQUESTED",
        "decided_by_user_id": None,
        "revocation_cause": None,
        "checked_in_at": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/break-housing-requests/<request_id>/decision" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def decide_request(request_id):
    stay = V.must_get("BreakHousingRequest", request_id)
    body = V.body()
    decision = V.s_enum(body, "decision", ("APPROVE", "DENY"))
    V.s_str(body, "reason", required=False)
    if stay["status"] != "REQUESTED":
        raise ApiError("ERR_BREAK_REQUEST_STATE_INVALID")
    if decision == "DENY":
        stay["status"] = "DENIED"
        stay["decided_by_user_id"] = g.user_id
        return responses.obj(stay)
    room = DB["rooms"].get(stay["room_id"])
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    building = derive.building_of_room(room)
    services.posture_gate(building)
    if building is not None and not building.get("break_housing_enabled"):
        raise ApiError("ERR_BREAK_HOUSING_DISABLED")
    student = DB["students"].get(stay["student_id"])
    if student is not None and not student.get("break_housing_eligible", True):
        raise ApiError("ERR_STUDENT_ON_PROBATION")
    projected = len(calc.colliding_break_holds(stay)) + 1
    if projected > room["bed_capacity"]:
        raise ApiError("ERR_BREAK_HOUSING_CAPACITY")
    stay["status"] = "APPROVED"
    stay["decided_by_user_id"] = g.user_id
    return responses.obj(stay)


@bp.route("%s/break-housing-requests/<request_id>/occupancy" % API_PREFIX, methods=["POST"])
@endpoint(RA_OR_DIRECTOR)
def occupancy(request_id):
    stay = V.must_get("BreakHousingRequest", request_id)
    body = V.body()
    action = V.s_enum(body, "action", ("CHECK_IN", "CLOSE"))
    V.s_str(body, "note", required=False)
    room = DB["rooms"].get(stay["room_id"])
    today = store.now().date().isoformat()
    if action == "CHECK_IN":
        if stay["status"] != "APPROVED":
            raise ApiError("ERR_BREAK_REQUEST_STATE_INVALID")
        if room is not None:
            services.room_posture_gate(room)
        if not (stay["start_date"] <= today <= stay["end_date"]):
            raise ApiError("ERR_BREAK_REQUEST_STATE_INVALID")
        stay["status"] = "CHECKED_IN"
        stay["checked_in_at"] = store.now_iso()
    else:
        if stay["status"] != "CHECKED_IN":
            raise ApiError("ERR_BREAK_REQUEST_STATE_INVALID")
        if room is not None:
            services.room_posture_gate(room)
        if not (today > stay["end_date"]):
            raise ApiError("ERR_BREAK_REQUEST_STATE_INVALID")
        stay["status"] = "CLOSED"
    return responses.obj(stay)
