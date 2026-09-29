"""Roommate mediation and the room-change placement track."""
from flask import Blueprint, g

import derive
import responses
import services
import store
import validators as V
from auth import endpoint, explicit_touch
from constants import API_PREFIX, MAX_MEDIATION_ROUNDS, RC_ORIGINS
from errors import ApiError
from store import DB

DIRECTOR = ["ResidenceDirector"]
STUDENT_OR_DIRECTOR = ["Student", "ResidenceDirector"]
bp = Blueprint("roomchange", __name__)


@bp.route("%s/room-change-cases" % API_PREFIX, methods=["POST"])
@endpoint(STUDENT_OR_DIRECTOR)
def create_case():
    body = V.body()
    student_id = V.s_id(body, "student_id")
    origin = V.s_enum(body, "origin", RC_ORIGINS)
    from_room_id = V.s_id(body, "from_room_id")
    expected_version = V.s_int(body, "expected_student_version", 0)
    roommate_id = V.s_id(body, "roommate_student_id", required=False)
    student = store.get("students", student_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    if store.get("rooms", from_room_id) is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    if roommate_id is not None and store.get("students", roommate_id) is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    if expected_version != student["version"]:
        raise ApiError("ERR_STALE_STUDENT_VERSION")
    if student.get("current_room_id") != from_room_id:
        raise ApiError("ERR_STUDENT_NOT_IN_ROOM")

    superseded_id = None
    for other in store.all_rows("rc_cases"):
        if other["student_id"] == student_id and other["placement_status"] == "REQUESTED":
            other["placement_status"] = "CANCELLED"
            superseded_id = other["id"]
    row = store.insert("rc_cases", "RoomChangeCase", {
        "student_id": student_id,
        "roommate_student_id": roommate_id,
        "from_room_id": from_room_id,
        "to_room_id": None,
        "origin": origin,
        "mediation_status": "INTAKE" if origin == "ROOMMATE_CONFLICT" else "NOT_REQUIRED",
        "placement_status": "NONE",
        "mediation_round": 0,
        "session_at": None,
        "opened_by_user_id": g.user_id,
        "superseded_case_id": superseded_id,
        "reverted_from_room_id": None,
    })
    explicit_touch(student)
    return responses.obj(row, 201)


@bp.route("%s/room-change-cases/<case_id>/mediation" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def mediation(case_id):
    case = V.must_get("RoomChangeCase", case_id)
    body = V.body()
    action = V.s_enum(body, "action", ("OPEN_INTAKE", "SCHEDULE_SESSION", "RECORD_SESSION"))
    session_at = V.s_dt(body, "session_at", required=(action == "SCHEDULE_SESSION"))
    outcome = V.s_enum(body, "outcome", ("AGREEMENT", "IMPASSE"),
                       required=(action == "RECORD_SESSION"))
    status = case["mediation_status"]
    if action == "OPEN_INTAKE":
        if status != "NOT_REQUIRED" or not case.get("roommate_student_id"):
            raise ApiError("ERR_MEDIATION_STATE_INVALID")
        case["mediation_status"] = "INTAKE"
    elif action == "SCHEDULE_SESSION":
        if status not in ("INTAKE", "IMPASSE"):
            raise ApiError("ERR_MEDIATION_STATE_INVALID")
        if case["mediation_round"] >= MAX_MEDIATION_ROUNDS:
            raise ApiError("ERR_MEDIATION_ROUND_LIMIT")
        if session_at <= store.now():
            raise ApiError("ERR_MEDIATION_STATE_INVALID")
        case["mediation_status"] = "SESSION_SCHEDULED"
        case["session_at"] = store.fmt_iso(session_at)
    else:
        if status != "SESSION_SCHEDULED":
            raise ApiError("ERR_MEDIATION_STATE_INVALID")
        case["mediation_round"] += 1
        case["mediation_status"] = (
            "AGREEMENT_REACHED" if outcome == "AGREEMENT" else "IMPASSE"
        )
    return responses.obj(case)


@bp.route("%s/room-change-cases/<case_id>/placement-request" % API_PREFIX, methods=["POST"])
@endpoint(STUDENT_OR_DIRECTOR)
def placement_request(case_id):
    case = V.must_get("RoomChangeCase", case_id)
    body = V.body()
    to_room_id = V.s_id(body, "to_room_id")
    room = store.get("rooms", to_room_id)
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    if case["placement_status"] != "NONE":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID")
    if case["origin"] == "ROOMMATE_CONFLICT" and case["mediation_status"] not in (
            "AGREEMENT_REACHED", "IMPASSE"):
        raise ApiError("ERR_PLACEMENT_STATE_INVALID")
    services.room_available_gate(room)
    student = DB["students"].get(case["student_id"])
    if student is not None and derive.student_standing(student) == "SUSPENDED":
        raise ApiError("ERR_STUDENT_ON_PROBATION")
    if to_room_id == case["from_room_id"]:
        raise ApiError("ERR_STUDENT_NOT_IN_ROOM")
    case["placement_status"] = "REQUESTED"
    case["to_room_id"] = to_room_id
    return responses.obj(case)


@bp.route("%s/room-change-cases/<case_id>/placement-decision" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def placement_decision(case_id):
    case = V.must_get("RoomChangeCase", case_id)
    body = V.body()
    decision = V.s_enum(body, "decision", ("APPROVE", "DENY"))
    V.s_str(body, "reason", required=False)
    if case["placement_status"] != "REQUESTED":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID")
    if decision == "DENY":
        case["placement_status"] = "DENIED"
        return responses.obj(case)
    room = DB["rooms"].get(case.get("to_room_id"))
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    services.room_posture_gate(room)
    services.room_available_gate(room)
    student = DB["students"].get(case["student_id"])
    if student is not None:
        if derive.student_standing(student) != "GOOD":
            raise ApiError("ERR_STUDENT_ON_PROBATION")
        if derive.student_judicial_hold(student):
            raise ApiError("ERR_JUDICIAL_HOLD")
    case["placement_status"] = "APPROVED"
    return responses.obj(case)


@bp.route("%s/room-change-cases/<case_id>/placement-completion" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def placement_completion(case_id):
    case = V.must_get("RoomChangeCase", case_id)
    body = V.body()
    V.s_str(body, "note", required=False)
    if case["placement_status"] != "APPROVED":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID")
    to_room = DB["rooms"].get(case.get("to_room_id"))
    if to_room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    services.room_posture_gate(to_room)
    services.room_available_gate(to_room)
    student = DB["students"].get(case["student_id"])
    from_room = DB["rooms"].get(case.get("from_room_id"))
    case["reverted_from_room_id"] = case.get("from_room_id")
    if student is not None:
        student["current_room_id"] = to_room["id"]
        student["housing_status"] = "ASSIGNED"
    if from_room is not None:
        services.sync_room_status(from_room)
    services.sync_room_status(to_room)
    case["placement_status"] = "COMPLETED"
    return responses.obj(case)


@bp.route("%s/room-change-cases/<case_id>/placement-revert" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def placement_revert(case_id):
    case = V.must_get("RoomChangeCase", case_id)
    body = V.body()
    V.s_str(body, "reason")
    if case["placement_status"] != "COMPLETED":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID")
    origin_room = DB["rooms"].get(case.get("reverted_from_room_id"))
    if origin_room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    if origin_room["status"] == "CONSOLIDATED":
        raise ApiError("ERR_ROOM_NOT_AVAILABLE")
    if derive.room_occupied_beds(origin_room) >= origin_room["bed_capacity"]:
        raise ApiError("ERR_ROOM_AT_CAPACITY")
    student = DB["students"].get(case["student_id"])
    to_room = DB["rooms"].get(case.get("to_room_id"))
    if student is not None:
        student["current_room_id"] = origin_room["id"]
        student["housing_status"] = "ASSIGNED"
    if to_room is not None:
        services.sync_room_status(to_room)
    services.sync_room_status(origin_room)
    case["placement_status"] = "REVERTED"
    return responses.obj(case)
