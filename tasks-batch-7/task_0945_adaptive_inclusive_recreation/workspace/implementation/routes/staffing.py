"""Staff members, certifications and assignments."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import Body, Refs, check_transition, endpoint, pagination, paginate, resolve_one
from envelope import ok, ok_list
from errors import ApiError
from store import date_of_instant, db, insert, parse_date, parse_instant, sort_rows, touch

bp = Blueprint("staffing", __name__)

ASSIGNMENT_TERMINALS = ("WITHDRAWN", "DELIVERED")


# ---------------------------------------------------------------------------
# staff members
# ---------------------------------------------------------------------------

@bp.route("/recreation/staff-members", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_staff_member(context):
    body = Body(context.body)
    fields = {
        "full_name": body.req_string("full_name"),
        "role_title": body.req_string("role_title"),
    }
    body.check_enums()
    return ok(serial.dump(insert("staff_members", fields)), 201)


@bp.route("/recreation/staff-members/<staff_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_staff_member(context, staff_id):
    return ok(serial.dump(resolve_one("staff", staff_id)))


# ---------------------------------------------------------------------------
# certifications
# ---------------------------------------------------------------------------

@bp.route("/recreation/staff-certifications", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_certification(context):
    staff_id = context.body.get("staff_member_id")
    if isinstance(staff_id, str):
        resolve_one("staff", staff_id)
    body = Body(context.body)
    fields = {
        "staff_member_id": body.req_string("staff_member_id"),
        "certification_type": body.req_enum("certification_type", enums.CERTIFICATION_TYPES),
        "issued_on": body.req_date("issued_on"),
        "expires_on": body.req_date("expires_on"),
        "status": "VALID",
    }
    body.check_enums()
    resolve_one("staff", fields["staff_member_id"])
    return ok(serial.dump(insert("staff_certifications", fields)), 201)


@bp.route("/recreation/staff-certifications", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_certifications(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("staff_certifications"))
    staff_id = context.q("staff_member_id")
    certification_type = context.q("certification_type")
    status = context.q("status")
    if staff_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_id]
    if certification_type is not None:
        rows = [r for r in rows if r["certification_type"] == certification_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/staff-certifications/<certification_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_certification(context, certification_id):
    return ok(serial.dump(resolve_one("certification", certification_id)))


@bp.route("/recreation/staff-certifications/<certification_id>/renew", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def renew_certification(context, certification_id):
    certification = resolve_one("certification", certification_id)
    body = Body(context.body)
    new_expires_on = body.req_date("new_expires_on")
    body.check_enums()
    check_transition(certification["status"], ("VALID", "EXPIRED"), ())
    new_day = parse_date(new_expires_on)
    if certification["status"] == "EXPIRED":
        if new_day < db.clock_date:
            raise ApiError("ERR_INVALID_STATE", "new_expires_on is before the logical clock date.")
    else:
        if new_day <= parse_date(certification["expires_on"]):
            raise ApiError(
                "ERR_INVALID_STATE", "new_expires_on must be later than the current expiry."
            )
    certification["expires_on"] = new_expires_on
    certification["status"] = "VALID"
    touch(certification)
    return ok(serial.dump(certification))


# ---------------------------------------------------------------------------
# assignments
# ---------------------------------------------------------------------------

@bp.route("/recreation/staff-assignments", methods=["POST"])
@endpoint(roles=("ActivityLead", "ProgramAdmin"))
def create_assignment(context):
    raw = context.body
    refs = Refs()
    if isinstance(raw.get("dedicated_participant_id"), str):
        refs.add("participant", raw["dedicated_participant_id"], path=False)
    if isinstance(raw.get("session_id"), str):
        refs.add("session", raw["session_id"], path=False)
    if isinstance(raw.get("staff_member_id"), str):
        refs.add("staff", raw["staff_member_id"], path=False)
    refs.resolve()

    body = Body(raw)
    session_id = body.req_string("session_id")
    staff_member_id = body.req_string("staff_member_id")
    assignment_role = body.req_enum("assignment_role", enums.ASSIGNMENT_ROLES)
    dedicated_participant_id = body.opt_string("dedicated_participant_id", None)
    body.check_enums()

    session = resolve_one("session", session_id)
    staff_member = resolve_one("staff", staff_member_id)
    if assignment_role == "ONE_TO_ONE":
        if dedicated_participant_id is None:
            raise ApiError(
                "ERR_VALIDATION", "dedicated_participant_id is required for a ONE_TO_ONE role."
            )
        resolve_one("participant", dedicated_participant_id)
    else:
        dedicated_participant_id = None

    program = L.program_of_session(session)
    today = db.clock_date
    session_date = date_of_instant(session["start_at"])

    has_all, unexpired_today = calc.staff_certification_verdict(
        staff_member["id"], program, today
    )
    if not has_all:                                                   # rung 39
        raise ApiError("ERR_STAFF_CERT_MISSING")
    if not unexpired_today:                                           # rung 40
        raise ApiError("ERR_STAFF_CERT_EXPIRED_AT_ASSIGNMENT")

    new_start = parse_instant(session["start_at"])                    # rung 42
    new_end = parse_instant(session["end_at"])
    buffer = timedelta(minutes=calc.STAFF_TURNAROUND_BUFFER_MINUTES)
    for existing in L.assignments_of_staff(staff_member["id"]):
        if existing["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        other = db.get("program_sessions", existing["session_id"])
        if other is None or other["status"] not in ("DRAFT", "OPEN", "STAFFING_LOCKED"):
            continue
        other_start = parse_instant(other["start_at"])
        other_end = parse_instant(other["end_at"])
        if new_start < other_end + buffer and other_start < new_end + buffer:
            raise ApiError("ERR_STAFF_TIME_CONFLICT")

    row = insert(
        "staff_assignments",
        {
            "session_id": session["id"],
            "staff_member_id": staff_member["id"],
            "dedicated_participant_id": dedicated_participant_id,
            "assignment_role": assignment_role,
            "qualified_at_assignment": True,
            "qualified_at_session_date": calc.staff_qualified(
                staff_member["id"], program, session_date
            ),
            "status": "PROPOSED",
        },
    )
    engine.refresh_session_counters(session)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/staff-assignments", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_assignments(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("staff_assignments"))
    session_id = context.q("session_id")
    staff_id = context.q("staff_member_id")
    dedicated = context.q("dedicated_participant_id")
    status = context.q("status")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if staff_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_id]
    if dedicated is not None:
        rows = [r for r in rows if r["dedicated_participant_id"] == dedicated]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/staff-assignments/<assignment_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_assignment(context, assignment_id):
    return ok(serial.dump(resolve_one("assignment", assignment_id)))


def _requalify(assignment, session):
    program = L.program_of_session(session)
    session_date = date_of_instant(session["start_at"])
    return calc.staff_certification_verdict(assignment["staff_member_id"], program, session_date)


@bp.route("/recreation/staff-assignments/<assignment_id>/confirm", methods=["POST"])
@endpoint(roles=("ActivityLead",))
def confirm_assignment(context, assignment_id):
    assignment = resolve_one("assignment", assignment_id)
    check_transition(assignment["status"], ("PROPOSED",), ASSIGNMENT_TERMINALS)
    session = db.get("program_sessions", assignment["session_id"])
    if session["status"] not in ("OPEN", "STAFFING_LOCKED"):
        raise ApiError("ERR_INVALID_STATE", "The session does not accept assignment confirmation.")
    has_all, unexpired = _requalify(assignment, session)
    if not has_all:
        raise ApiError("ERR_STAFF_CERT_MISSING")
    if not unexpired:
        raise ApiError("ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION")
    assignment["qualified_at_session_date"] = True
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    engine.refresh_session_counters(session)
    return ok(serial.dump(assignment))


@bp.route("/recreation/staff-assignments/<assignment_id>/withdraw", methods=["POST"])
@endpoint(roles=("ActivityLead", "ProgramAdmin"))
def withdraw_assignment(context, assignment_id):
    assignment = resolve_one("assignment", assignment_id)
    check_transition(
        assignment["status"], ("PROPOSED", "CONFIRMED", "LAPSED"), ASSIGNMENT_TERMINALS
    )
    session = db.get("program_sessions", assignment["session_id"])
    if assignment["status"] == "CONFIRMED" and session["status"] == "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "The session has already been delivered.")
    previous = assignment["status"]
    assignment["status"] = "WITHDRAWN"
    touch(assignment)
    if previous in ("PROPOSED", "CONFIRMED"):
        engine.refresh_session_counters(session)
    return ok(serial.dump(assignment))


@bp.route("/recreation/staff-assignments/<assignment_id>/revalidate", methods=["POST"])
@endpoint(roles=("ActivityLead",))
def revalidate_assignment(context, assignment_id):
    assignment = resolve_one("assignment", assignment_id)
    check_transition(assignment["status"], ("LAPSED",), ASSIGNMENT_TERMINALS)
    session = db.get("program_sessions", assignment["session_id"])
    if session["status"] not in ("OPEN", "STAFFING_LOCKED"):
        raise ApiError("ERR_INVALID_STATE", "The session does not accept revalidation.")
    has_all, unexpired = _requalify(assignment, session)
    if not has_all:
        raise ApiError("ERR_STAFF_CERT_MISSING")
    if not unexpired:
        raise ApiError("ERR_STAFF_CERT_EXPIRES_BEFORE_SESSION")
    assignment["qualified_at_session_date"] = True
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    engine.refresh_session_counters(session)
    return ok(serial.dump(assignment))
