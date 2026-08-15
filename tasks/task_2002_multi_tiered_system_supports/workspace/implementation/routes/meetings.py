"""Team meeting endpoints: schedule, convene, ratify, reject, minute (+ aliases)."""

from flask import Blueprint, request

from db import DB
from errors import (
    err, ERR_MEETING_NOT_FOUND, ERR_MOVEMENT_NOT_FOUND, ERR_SCHOOL_NOT_FOUND,
    ERR_INVALID_STATE,
)
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_date, base_fields, paginate, sort_created, touch,
)
from response import success_object, success_list
from routes.plans import _check_student_occ
from services import (
    serialize_meeting, serialize_movement,
    resolve_school, resolve_meeting, ratify_movement,
)

bp = Blueprint("meetings", __name__)


@bp.post("/districts/<districtId>/schools/<schoolId>/team-meetings")
def create_meeting(districtId, schoolId):
    require_role("TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"scheduled_on"})
    require_fields(body, ["scheduled_on"])
    scheduled_on = req_date(body, "scheduled_on")
    resolve_school(districtId, schoolId)
    m = base_fields()
    m.update({
        "school_id": schoolId,
        "scheduled_on": scheduled_on,
        "status": "SCHEDULED",
        "minuted_movement_count": 0,
    })
    DB.team_meetings[m["id"]] = m
    return success_object(serialize_meeting(m), status=201)


def _list_meetings(schoolId):
    status_filter = request.args.get("status")
    items = [m for m in DB.team_meetings.values() if m["school_id"] == schoolId]
    if status_filter is not None:
        items = [m for m in items if m["status"] == status_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_meeting(m) for m in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/team-meetings")
def list_meetings(districtId, schoolId):
    require_role(*ALL_ROLES)
    resolve_school(districtId, schoolId)
    return _list_meetings(schoolId)


@bp.get("/districts/<districtId>/schools/<schoolId>/team-meetings/<meetingId>")
def get_meeting(districtId, schoolId, meetingId):
    require_role(*ALL_ROLES)
    m = resolve_meeting(districtId, schoolId, meetingId)
    return success_object(serialize_meeting(m))


@bp.post("/districts/<districtId>/schools/<schoolId>/team-meetings/<meetingId>/convene")
def convene_meeting(districtId, schoolId, meetingId):
    require_role("TeamLead")
    m = resolve_meeting(districtId, schoolId, meetingId)
    if m["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, 409, "Only a SCHEDULED meeting can be convened")
    m["status"] = "CONVENED"
    touch(m)
    return success_object(serialize_meeting(m))


def _resolve_movement_for_meeting(schoolId, movement_id):
    """Body-FK existence for ratify/reject: the movement must exist and belong to
    a student of this school."""
    mv = DB.tier_movements.get(movement_id)
    if mv is None:
        raise err(ERR_MOVEMENT_NOT_FOUND, 404, "movement_id does not exist")
    student = DB.students.get(mv["student_id"])
    if student is None or student["school_id"] != schoolId:
        raise err(ERR_MOVEMENT_NOT_FOUND, 404, "movement_id does not exist (within school)")
    return mv, student


@bp.post("/districts/<districtId>/schools/<schoolId>/team-meetings/<meetingId>/ratify")
def ratify_at_meeting(districtId, schoolId, meetingId):
    require_role("TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"movement_id", "expected_student_version"})
    require_fields(body, ["movement_id", "expected_student_version"])
    movement_id = req_string(body, "movement_id")
    m = resolve_meeting(districtId, schoolId, meetingId)
    mv, student = _resolve_movement_for_meeting(schoolId, movement_id)
    # OCC on the student guards against ratifying from a stale view (PRD §2.9).
    _check_student_occ(body, student)
    if m["status"] != "CONVENED":
        raise err(ERR_INVALID_STATE, 409, "Meeting must be CONVENED to ratify")
    if mv["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, 409, "Movement is not PROPOSED")
    # Only the freshest proposal for a student is ratifiable.
    later_proposed = any(
        other["status"] == "PROPOSED"
        and (other["created_at"], other["_seq"]) > (mv["created_at"], mv["_seq"])
        for other in DB.tier_movements.values()
        if other["student_id"] == mv["student_id"] and other["id"] != mv["id"]
    )
    if later_proposed:
        raise err(ERR_INVALID_STATE, 409,
                  "A newer PROPOSED movement supersedes this one for the student")
    ratify_movement(m, mv)
    return success_object(serialize_movement(mv))


@bp.post("/districts/<districtId>/schools/<schoolId>/team-meetings/<meetingId>/reject")
def reject_at_meeting(districtId, schoolId, meetingId):
    require_role("TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"movement_id"})
    require_fields(body, ["movement_id"])
    movement_id = req_string(body, "movement_id")
    m = resolve_meeting(districtId, schoolId, meetingId)
    mv, _student = _resolve_movement_for_meeting(schoolId, movement_id)
    if m["status"] != "CONVENED":
        raise err(ERR_INVALID_STATE, 409, "Meeting must be CONVENED to reject")
    if mv["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, 409, "Movement is not PROPOSED")
    mv["status"] = "REJECTED"
    touch(mv)
    return success_object(serialize_movement(mv))


@bp.post("/districts/<districtId>/schools/<schoolId>/team-meetings/<meetingId>/minute")
def minute_meeting(districtId, schoolId, meetingId):
    require_role("TeamLead")
    m = resolve_meeting(districtId, schoolId, meetingId)
    if m["status"] != "CONVENED":
        raise err(ERR_INVALID_STATE, 409, "Only a CONVENED meeting can be minuted")
    # A meeting cannot be minuted while proposals are still pending at its school
    # (PRD §3.7).
    pending = any(
        mv["status"] == "PROPOSED"
        and DB.students.get(mv["student_id"]) is not None
        and DB.students[mv["student_id"]]["school_id"] == schoolId
        for mv in DB.tier_movements.values()
    )
    if pending:
        raise err(ERR_INVALID_STATE, 409,
                  "Meeting has proposals still pending resolution")
    m["status"] = "MINUTED"
    touch(m)
    return success_object(serialize_meeting(m))


# ---------- Flat aliases ----------

@bp.get("/team-meetings/<meetingId>")
def get_meeting_flat(meetingId):
    require_role(*ALL_ROLES)
    m = DB.team_meetings.get(meetingId)
    if m is None:
        raise err(ERR_MEETING_NOT_FOUND, 404, "meetingId does not exist")
    return success_object(serialize_meeting(m))


@bp.get("/schools/<id>/team-meetings")
def list_meetings_flat(id):
    require_role(*ALL_ROLES)
    s = DB.schools.get(id)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "school id does not exist")
    return _list_meetings(id)


@bp.get("/team-meetings/<id>/tier-movements")
def list_movements_for_meeting(id):
    require_role(*ALL_ROLES)
    m = DB.team_meetings.get(id)
    if m is None:
        raise err(ERR_MEETING_NOT_FOUND, 404, "meeting id does not exist")
    items = sort_created(
        mv for mv in DB.tier_movements.values() if mv["decided_at_meeting_id"] == id
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_movement(mv) for mv in page], limit, offset, total)
