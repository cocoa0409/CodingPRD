"""Training sessions and attendance (PRD §3.5)."""

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_common, touch, paginate, sorted_by_created

bp = Blueprint("training", __name__)

LEVELS = ["BASIC", "ADVANCED", "LEAD_CERT"]


def session_view(s):
    return {
        "id": s["id"],
        "topic": s["topic"],
        "level": s["level"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "credit_hours": s["credit_hours"],
        "capacity": s["capacity"],
        "enrolled_count": s["enrolled_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def attendance_view(a):
    return {
        "id": a["id"],
        "session_id": a["session_id"],
        "volunteer_id": a["volunteer_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _get_session(session_id):
    session = db.training_sessions.get(session_id)
    if session is None:
        raise ApiError("ERR_NOT_FOUND", f"TrainingSession {session_id} does not exist")
    return session


@bp.post("/training-sessions")
def create_session():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "topic": {"type": "string", "required": True},
        "level": {"type": "string", "required": True, "enum": LEVELS},
        "scheduled_start": {"type": "string", "required": True},
        "scheduled_end": {"type": "string", "required": True},
        "credit_hours": {"type": "integer", "required": True, "min_int": 1},
        "capacity": {"type": "integer", "required": True, "min_int": 1},
    })
    try:
        start = _parse_iso(body["scheduled_start"])
        end = _parse_iso(body["scheduled_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "scheduled_start/scheduled_end must be ISO-8601 instants")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "scheduled_end must be after scheduled_start")
    session = make_common()
    session.update({
        "topic": body["topic"],
        "level": body["level"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "credit_hours": body["credit_hours"],
        "capacity": body["capacity"],
        "enrolled_count": 0,
        "status": "SCHEDULED",
    })
    db.training_sessions[session["id"]] = session
    return success(session_view(session), status=201)


@bp.get("/training-sessions/<session_id>")
def get_session(session_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    return success(session_view(_get_session(session_id)))


@bp.get("/training-sessions")
def list_sessions():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.training_sessions.values())
    for param in ("status", "level"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([session_view(s) for s in page], pagination=pg)


@bp.post("/training-sessions/<session_id>/enroll")
def enroll(session_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"volunteer_id": {"type": "string", "required": True}})
    session = _get_session(session_id)
    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {body['volunteer_id']} does not exist")
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session accepts enrollments")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot enroll")
    if any(a["session_id"] == session["id"] and a["volunteer_id"] == vol["id"]
           for a in db.attendances.values()):
        raise ApiError("ERR_ALREADY_ENROLLED", "Volunteer is already enrolled in this session")
    if session["enrolled_count"] >= session["capacity"]:
        raise ApiError("ERR_TRAINING_FULL", "Session is at capacity")

    attendance = make_common()
    attendance.update({
        "session_id": session["id"],
        "volunteer_id": vol["id"],
        "status": "ENROLLED",
    })
    db.attendances[attendance["id"]] = attendance
    session["enrolled_count"] += 1
    touch(session)
    return success(attendance_view(attendance), status=201)


@bp.post("/training-sessions/<session_id>/complete")
def complete_session(session_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"marks": {"type": "array", "required": True}})
    session = _get_session(session_id)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session can be completed")

    marks = body["marks"]
    normalized = []
    for mark in marks:
        if not isinstance(mark, dict) or not isinstance(mark.get("attendance_id"), str):
            raise ApiError("ERR_VALIDATION", "Each mark must carry an attendance_id")
        outcome = mark.get("outcome")
        if outcome not in ("ATTENDED", "NO_SHOW"):
            raise ApiError("ERR_VALIDATION", "Each mark outcome must be ATTENDED or NO_SHOW")
        normalized.append((mark["attendance_id"], outcome))

    enrolled = [a for a in db.attendances.values()
                if a["session_id"] == session["id"] and a["status"] == "ENROLLED"]
    enrolled_ids = {a["id"] for a in enrolled}
    marked_ids = [m[0] for m in normalized]
    if (len(marked_ids) != len(set(marked_ids))
            or set(marked_ids) != enrolled_ids):
        raise ApiError("ERR_ATTENDANCE_MARKS_INCOMPLETE",
                       "Marks must cover every ENROLLED attendance exactly once")

    # Temporal gate: clock must have reached scheduled_end.
    if db.now() < _parse_iso(session["scheduled_end"]):
        raise ApiError("ERR_SESSION_NOT_ENDED", "The session has not ended yet")

    for attendance_id, outcome in normalized:
        attendance = db.attendances[attendance_id]
        attendance["status"] = outcome
        touch(attendance)
        if outcome == "ATTENDED":
            vol = db.volunteers.get(attendance["volunteer_id"])
            if vol is not None:
                vol["training_hours"] += session["credit_hours"]
                vol["sessions_attended"] += 1
                touch(vol)
    session["status"] = "COMPLETED"
    touch(session)
    return success(session_view(session))


@bp.post("/training-sessions/<session_id>/cancel")
def cancel_session(session_id):
    require_roles("ShopCoordinator")
    session = _get_session(session_id)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED session can be cancelled")
    for a in db.attendances.values():
        if a["session_id"] == session["id"] and a["status"] == "ENROLLED":
            a["status"] = "DROPPED"
            touch(a)
    session["status"] = "CANCELLED"
    touch(session)
    return success(session_view(session))


@bp.get("/attendances/<attendance_id>")
def get_attendance(attendance_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    row = db.attendances.get(attendance_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", f"TrainingAttendance {attendance_id} does not exist")
    return success(attendance_view(row))


@bp.get("/attendances")
def list_attendances():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.attendances.values())
    for param in ("session_id", "volunteer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [a for a in rows if a[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([attendance_view(a) for a in page], pagination=pg)
