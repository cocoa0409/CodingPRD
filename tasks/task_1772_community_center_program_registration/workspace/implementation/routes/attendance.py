"""AttendanceRecord endpoints (PRD 3.9)."""
from flask import Blueprint, request

import clock
import services
import store
from auth import authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    req_enum,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("attendance", __name__)

FIELDS = [
    "id",
    "meeting_id",
    "registration_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

MARK_ROLES = ["Instructor", "FrontDeskStaff"]
READ_ROLES = ["Instructor", "FrontDeskStaff", "ProgramCoordinator"]
MARKS = ["PRESENT", "ABSENT", "EXCUSED"]


def attendance_out(rec):
    return serialize(rec, FIELDS)


def _check_instructor_identity(uid, role, session):
    """Entity-backed identity: an Instructor may mark/correct only sessions
    assigned to them (PRD 2.1); FrontDeskStaff is exempt."""
    if role == "Instructor" and session["instructor_id"] != uid:
        raise_err("ERR_UNAUTHORIZED_ROLE", "Instructors may only mark attendance for their own sessions")


@bp.route("/attendance-records", methods=["POST"])
def create_attendance():
    uid, role = authenticate()
    authorize(role, MARK_ROLES)
    body = body_json()
    meeting_id = req_str(body, "meeting_id")
    registration_id = req_str(body, "registration_id")
    status = req_enum(body, "status", MARKS)
    meeting = get_or_404(store.meetings, meeting_id, "ClassMeeting")
    session = get_or_404(store.sessions, meeting["session_id"], "ClassSession")
    _check_instructor_identity(uid, role, session)
    reg = get_or_404(store.registrations, registration_id, "Registration")
    if reg["session_id"] != meeting["session_id"]:
        raise_err("ERR_NOT_FOUND", "Registration does not belong to the meeting's session")
    # Four gates in pinned order (PRD 3.9).
    if reg["enrollment_status"] != "ENROLLED":
        raise_err("ERR_REGISTRATION_NOT_ENROLLED", "Attendance can only be marked for an ENROLLED registration")
    season = services.season_of_session(session)
    verified = False
    for f in store.safety_forms.values():
        if (
            f["participant_id"] == reg["participant_id"]
            and season is not None
            and f["season_id"] == season["id"]
            and f["status"] == "VERIFIED"
        ):
            verified = True
            break
    if not verified:
        raise_err("ERR_SAFETY_FORM_REQUIRED", "A VERIFIED safety form is required for this participant and season")
    if clock.now() < meeting["starts_at"]:
        raise_err("ERR_ATTENDANCE_TOO_EARLY", "The meeting has not started yet")
    for a in store.attendance.values():
        if a["meeting_id"] == meeting_id and a["registration_id"] == registration_id:
            raise_err("ERR_DUPLICATE_ATTENDANCE", "An attendance record already exists for this meeting and registration")
    rec = new_record()
    rec.update(meeting_id=meeting_id, registration_id=registration_id, status=status)
    store.attendance[rec["id"]] = rec
    services.replay_absences(reg)
    return success_object(attendance_out(rec), 201)


@bp.route("/attendance-records", methods=["GET"])
def list_attendance():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    meeting_id = request.args.get("meeting_id")
    registration_id = request.args.get("registration_id")
    records = list(store.attendance.values())
    if meeting_id is not None:
        records = [r for r in records if r["meeting_id"] == meeting_id]
    if registration_id is not None:
        records = [r for r in records if r["registration_id"] == registration_id]
    return list_response(records, attendance_out)


@bp.route("/attendance-records/<attendance_id>", methods=["GET"])
def get_attendance(attendance_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.attendance, attendance_id, "AttendanceRecord")
    return success_object(attendance_out(rec), 200)


@bp.route("/attendance-records/<attendance_id>", methods=["PATCH"])
def patch_attendance(attendance_id):
    uid, role = authenticate()
    authorize(role, MARK_ROLES)
    body = body_json()
    status = req_enum(body, "status", MARKS)
    rec = get_or_404(store.attendance, attendance_id, "AttendanceRecord")
    meeting = get_or_404(store.meetings, rec["meeting_id"], "ClassMeeting")
    session = get_or_404(store.sessions, meeting["session_id"], "ClassSession")
    _check_instructor_identity(uid, role, session)
    if session["status"] not in ("PUBLISHED", "ACTIVE"):
        raise_err("ERR_INVALID_STATE", "Attendance may be corrected only while the session is PUBLISHED or ACTIVE")
    rec["status"] = status
    bump(rec)
    reg = store.registrations.get(rec["registration_id"])
    if reg is not None:
        services.replay_absences(reg)
    return success_object(attendance_out(rec), 200)
