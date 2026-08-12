"""Session and InstructorAssignment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_new, store, touch
from errors import fail
from middleware import check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lifecycle, lookups
from services.calculations import credential_match_score
from util import body_json, fmt_dt, pagination_args, parse_dt, req_str, require_dt

bp = Blueprint("sessions", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

VENUE_KIND_FOR_MODE = {"ON_CAMPUS": "CAMPUS_LAB", "ON_SITE": "EMPLOYER_SITE"}


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@bp.route("/ct/cohorts/<cid>/sessions", methods=["POST"])
def create_session(cid):
    require_roles("WorkforceCoordinator")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    body = body_json()
    venue_id = req_str(body, "venue_id")
    start_at = require_dt(body.get("start_at"), "start_at")
    end_at = require_dt(body.get("end_at"), "end_at")
    if end_at <= start_at:
        fail("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    venue = store["venues"].get(venue_id)
    if venue is None:
        fail("ERR_INVALID_REQUEST", f"venue_id {venue_id} does not exist")
    if cohort["delivery_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Cannot plan sessions on a cohort in {cohort['delivery_status']}")
    buffer = timedelta(minutes=venue.get("turnover_buffer_minutes", 30))
    for other in store["sessions"].values():
        if other["venue_id"] != venue_id or other["status"] not in ("PLANNED", "HELD"):
            continue
        other_start = parse_dt(other["start_at"])
        other_end = parse_dt(other["end_at"])
        if start_at < other_end + buffer and other_start < end_at + buffer:
            fail("ERR_VENUE_OVERLAP", "The venue has a conflicting booking within the turnover buffer")
    expected_kind = VENUE_KIND_FOR_MODE[cohort["delivery_mode"]]
    if venue["kind"] != expected_kind:
        fail(
            "ERR_DELIVERY_MODE_MISMATCH",
            f"Venue kind {venue['kind']} is inconsistent with cohort delivery mode {cohort['delivery_mode']}",
        )
    hours = round((end_at - start_at).total_seconds() / 3600.0, 6)
    rec = stamp_new(
        {
            "id": db.new_id(),
            "cohort_id": cid,
            "venue_id": venue_id,
            "start_at": fmt_dt(start_at),
            "end_at": fmt_dt(end_at),
            "hours": hours,
            "status": "PLANNED",
            "attendance_closed": False,
            "_attendance": {},
        }
    )
    store["sessions"][rec["id"]] = rec
    touch(cohort)  # schedule mutation advances the cohort's version
    return ok(serialize(rec), 201)


@bp.route("/ct/sessions/<sid>", methods=["GET"])
def get_session(sid):
    uid, role = require_roles(*READ_ROLES)
    session = lookups.get_or_404("sessions", sid, "Session")
    check_employer_scope(uid, role, lookups.employer_id_of_session(session))
    return ok(serialize(session))


@bp.route("/ct/sessions", methods=["GET"])
def list_sessions():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["sessions"].values())
    if role == "EmployerContact":
        items = [s for s in items if lookups.employer_id_of_session(s) == uid]
    f_venue = request.args.get("venue_id")
    f_cohort = request.args.get("cohort_id")
    f_status = request.args.get("status")
    if f_venue is not None:
        items = [s for s in items if s["venue_id"] == f_venue]
    if f_cohort is not None:
        items = [s for s in items if s["cohort_id"] == f_cohort]
    if f_status is not None:
        items = [s for s in items if s["status"] == f_status]
    return _paginate(items)


@bp.route("/ct/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    require_roles("WorkforceCoordinator")
    session = lookups.get_or_404("sessions", sid, "Session")
    if session["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", f"Cannot cancel a session in {session['status']}")
    lifecycle.cancel_session_cascade(session)
    cohort = store["cohorts"].get(session["cohort_id"])
    if cohort is not None:
        lifecycle.maybe_advance_cohort_delivery(cohort)
        touch(cohort)
    return ok(serialize(session))


@bp.route("/ct/sessions/<sid>/close_attendance", methods=["POST"])
def close_attendance(sid):
    uid, _role = require_roles("Instructor")
    session = lookups.get_or_404("sessions", sid, "Session")
    if session["status"] == "CANCELLED":
        fail("ERR_INVALID_STATE", "Cannot close attendance on a CANCELLED session")
    # Entity-backed ownership: caller must hold a CONFIRMED (or, for idempotent
    # double-close detection, a COMPLETED) assignment on this session.
    owned = False
    for assignment in lookups.assignments_of_session(sid):
        if assignment["instructor_id"] == uid and assignment["status"] in ("CONFIRMED", "COMPLETED"):
            owned = True
            break
    if not owned:
        fail(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Caller is not the CONFIRMED instructor of an assignment on this session",
        )
    body = body_json()
    attendance = body.get("attendance")
    if not isinstance(attendance, list):
        fail("ERR_INVALID_REQUEST", "Field 'attendance' is required and must be a list")
    entries = []
    for entry in attendance:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each attendance entry must be an object")
        ref = entry.get("external_employee_ref")
        hours = entry.get("attended_hours")
        if not isinstance(ref, str) or not ref:
            fail("ERR_INVALID_REQUEST", "Each attendance entry requires 'external_employee_ref'")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours < 0:
            fail("ERR_INVALID_REQUEST", "Each attendance entry requires non-negative 'attended_hours'")
        if float(hours) > float(session["hours"]):
            fail("ERR_INVALID_REQUEST", "attended_hours may not exceed the session's hours")
        entries.append((ref, float(hours)))
    if session["status"] == "HELD" or session["attendance_closed"]:
        fail("ERR_ATTENDANCE_ALREADY_CLOSED", "Attendance for this session is already closed")
    if session["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", f"Cannot close attendance on a session in {session['status']}")
    cohort = store["cohorts"][session["cohort_id"]]
    if cohort["delivery_status"] not in ("LAUNCHED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", f"The cohort is in {cohort['delivery_status']}")

    participants_by_ref = {
        p["external_employee_ref"]: p for p in lookups.participants_of_cohort(cohort["id"])
    }
    for ref, hours in entries:
        participant = participants_by_ref.get(ref)
        if participant is None:
            continue
        participant["attended_hours"] = round(float(participant["attended_hours"]) + hours, 6)
        session["_attendance"][ref] = session["_attendance"].get(ref, 0) + hours
        touch(participant)
    session["attendance_closed"] = True
    session["status"] = "HELD"
    touch(session)
    for assignment in lookups.assignments_of_session(sid):
        if assignment["status"] == "CONFIRMED":
            assignment["status"] = "COMPLETED"
            touch(assignment)
            instructor = store["instructors"].get(assignment["instructor_id"])
            if instructor is not None:
                instructor["committed_hours"] = round(
                    float(instructor["committed_hours"]) - float(session["hours"]), 10
                )
                touch(instructor)
    lifecycle.maybe_advance_cohort_delivery(cohort)
    return ok(serialize(session))


@bp.route("/ct/sessions/<sid>/instructor-assignments", methods=["GET"])
def list_session_assignments(sid):
    uid, role = require_roles(*READ_ROLES)
    session = lookups.get_or_404("sessions", sid, "Session")
    check_employer_scope(uid, role, lookups.employer_id_of_session(session))
    return _paginate(lookups.assignments_of_session(sid))


# ---------------------------------------------------------------------------
# InstructorAssignments
# ---------------------------------------------------------------------------

@bp.route("/ct/sessions/<sid>/instructor-assignments", methods=["POST"])
def propose_assignment(sid):
    uid, _role = require_roles("WorkforceCoordinator")
    session = lookups.get_or_404("sessions", sid, "Session")
    body = body_json()
    instructor_id = req_str(body, "instructor_id")
    instructor = store["instructors"].get(instructor_id)
    if instructor is None:
        fail("ERR_INVALID_REQUEST", f"instructor_id {instructor_id} does not exist")
    if session["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", f"Cannot propose an assignment on a session in {session['status']}")
    rec = stamp_new(
        {
            "id": db.new_id(),
            "session_id": sid,
            "instructor_id": instructor_id,
            "proposed_by_user_id": uid,
            "approved_by_user_id": None,
            "match_score": None,
            "status": "PROPOSED",
        }
    )
    store["assignments"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/instructor-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    uid, role = require_roles(*READ_ROLES)
    assignment = lookups.get_or_404("assignments", aid, "InstructorAssignment")
    session = store["sessions"].get(assignment["session_id"])
    if session is not None:
        check_employer_scope(uid, role, lookups.employer_id_of_session(session))
    return ok(serialize(assignment))


@bp.route("/ct/instructor-assignments", methods=["GET"])
def list_assignments():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["assignments"].values())
    if role == "EmployerContact":
        scoped = []
        for a in items:
            session = store["sessions"].get(a["session_id"])
            if session is not None and lookups.employer_id_of_session(session) == uid:
                scoped.append(a)
        items = scoped
    f_instructor = request.args.get("instructor_id")
    f_session = request.args.get("session_id")
    f_status = request.args.get("status")
    if f_instructor is not None:
        items = [a for a in items if a["instructor_id"] == f_instructor]
    if f_session is not None:
        items = [a for a in items if a["session_id"] == f_session]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return _paginate(items)


@bp.route("/ct/instructor-assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    uid, _role = require_roles("CredentialOfficer")
    assignment = lookups.get_or_404("assignments", aid, "InstructorAssignment")
    if assignment["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", f"Cannot confirm an assignment in {assignment['status']}")
    session = store["sessions"][assignment["session_id"]]
    instructor = store["instructors"][assignment["instructor_id"]]
    cohort = store["cohorts"][session["cohort_id"]]
    if instructor["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The instructor is not ACTIVE")
    if session["status"] != "PLANNED":
        fail("ERR_SESSION_NOT_PLANNED", "The session is not PLANNED")
    match_score, expired_code = credential_match_score(instructor, session, cohort)
    if expired_code is not None:
        fail(
            "ERR_CREDENTIAL_EXPIRED",
            f"Required credential '{expired_code}' is expired at the session start",
        )
    if match_score < 80:
        fail("ERR_CREDENTIAL_MISMATCH", f"match_score {match_score} is below 80")
    if uid == assignment["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The proposer may not confirm their own proposal")
    start_at = parse_dt(session["start_at"])
    end_at = parse_dt(session["end_at"])
    for other_assignment in store["assignments"].values():
        if (
            other_assignment["instructor_id"] != assignment["instructor_id"]
            or other_assignment["status"] != "CONFIRMED"
            or other_assignment["id"] == assignment["id"]
        ):
            continue
        other_session = store["sessions"].get(other_assignment["session_id"])
        if other_session is None or other_session["status"] != "PLANNED":
            continue
        other_start = parse_dt(other_session["start_at"])
        other_end = parse_dt(other_session["end_at"])
        if start_at < other_end and other_start < end_at:
            fail(
                "ERR_INSTRUCTOR_DOUBLE_BOOKED",
                "The instructor holds a CONFIRMED assignment on an overlapping session",
            )
    assignment["match_score"] = match_score
    assignment["approved_by_user_id"] = uid
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    instructor["committed_hours"] = round(
        float(instructor["committed_hours"]) + float(session["hours"]), 10
    )
    touch(instructor)
    return ok(serialize(assignment))


@bp.route("/ct/instructor-assignments/<aid>/release", methods=["POST"])
def release_assignment(aid):
    require_roles("WorkforceCoordinator", "CredentialOfficer")
    assignment = lookups.get_or_404("assignments", aid, "InstructorAssignment")
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_INVALID_STATE", f"Cannot release an assignment in {assignment['status']}")
    session = store["sessions"][assignment["session_id"]]
    if assignment["status"] == "CONFIRMED":
        if session["status"] != "PLANNED":
            fail("ERR_INVALID_STATE", "Cannot release a CONFIRMED assignment on a non-PLANNED session")
        instructor = store["instructors"].get(assignment["instructor_id"])
        if instructor is not None:
            instructor["committed_hours"] = round(
                float(instructor["committed_hours"]) - float(session["hours"]), 10
            )
            touch(instructor)
    assignment["status"] = "RELEASED"
    touch(assignment)
    return ok(serialize(assignment))
