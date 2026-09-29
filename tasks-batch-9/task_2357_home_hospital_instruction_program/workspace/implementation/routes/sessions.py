"""Session scheduling, delivery, attendance coding and corrections (PRD §3.6)."""

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import (
    ABSENCE_KINDS,
    IN_SERVICE,
    SESSION_MODES,
    SESSION_OUTCOMES,
    SESSION_STATUSES,
    SUBJECTS,
    VOID_REASONS,
    listing,
)
from services import logic
from validation import fail, parse_date, parse_datetime

bp = Blueprint("sessions", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "HomeboundTeacher"]

MISSED_STATES = logic.MISSED_SESSION_STATES

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "assignment_id": {"type": "string", "required": True},
    "scheduled_start": {"type": "datetime", "required": True},
    "scheduled_end": {"type": "datetime", "required": True},
    "delivery_mode": {"type": "string", "required": True, "enum": SESSION_MODES},
    "subject": {"type": "string", "required": True, "enum": SUBJECTS},
    "escort_confirmed": {"type": "boolean"},
}

MAKEUP_BODY = {
    "assignment_id": {"type": "string", "required": True},
    "scheduled_start": {"type": "datetime", "required": True},
    "scheduled_end": {"type": "datetime", "required": True},
    "delivery_mode": {"type": "string", "required": True, "enum": SESSION_MODES},
    "subject": {"type": "string", "required": True, "enum": SUBJECTS},
    "escort_confirmed": {"type": "boolean"},
}

LOG_BODY = {
    "outcome": {"type": "string", "required": True, "enum": SESSION_OUTCOMES},
    "actual_minutes": {"type": "integer", "min": 0},
    "absence_kind": {"type": "string", "enum": ABSENCE_KINDS},
    "outcome_reason": {"type": "string"},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "assignment_id": {"type": "string"},
    "makeup_for_session_id": {"type": "string"},
    "status": {"type": "string", "enum": SESSION_STATUSES},
    "service_date": {"type": "date"},
}


def load_session(session_id):
    row = db.get("sessions", session_id)
    if row is None:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    return row


def _span(body):
    """Tier 3: the scheduled span must be positive and inside one UTC date."""
    start = parse_datetime(body["scheduled_start"])
    end = parse_datetime(body["scheduled_end"])
    if end <= start:
        fail("scheduled_end must be strictly later than scheduled_start.")
    if start.date() != end.date():
        fail("scheduled_start and scheduled_end must fall on the same UTC calendar date.")
    minutes = int((end - start).total_seconds() // 60)
    return start, end, minutes


def _rule_of(case):
    rule = db.get("entitlement_rules", case["entitlement_rule_id"])
    if rule is None:
        raise ApiError("ERR_NO_PUBLISHED_ENTITLEMENT_RULE")
    return rule


def _schedule(case, assignment, body, start, end, minutes, makeup_for=None):
    """Every scheduling check, in tier order, then the insert."""
    if case["service_status"] not in IN_SERVICE:                  # tier 8
        raise ApiError("ERR_CASE_NOT_ACTIVE")
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")

    session_mode = body["delivery_mode"]
    service_date = start.date()
    teacher = logic.teacher_of(assignment)
    logic.check_scheduling_safety(                                 # tier 10
        case, teacher, session_mode, body.get("escort_confirmed"), service_date
    )

    rule = _rule_of(case)
    if not (rule["min_session_minutes"] <= minutes <= rule["max_session_minutes"]):
        raise ApiError("ERR_SESSION_DURATION_INVALID")             # tier 11

    if assignment["case_id"] != case["id"]:                        # tier 12
        raise ApiError("ERR_ASSIGNMENT_CASE_MISMATCH")
    window_start = parse_date(case["certified_start_date"] or "")
    window_end = parse_date(case["certified_end_date"] or "")
    if (
        window_start is None
        or window_end is None
        or not (window_start <= service_date <= window_end)
    ):
        raise ApiError("ERR_SESSION_OUTSIDE_CERT_WINDOW")
    if makeup_for is not None:
        if makeup_for["status"] not in MISSED_STATES:
            raise ApiError("ERR_MAKEUP_NOT_ELIGIBLE")
        for other in db.rows("sessions"):
            if other.get("makeup_for_session_id") == makeup_for["id"]:
                raise ApiError("ERR_MAKEUP_NOT_ELIGIBLE")

    logic.check_slot_conflict(assignment, start, end, session_mode, rule)   # tier 13
    logic.check_min_gap(case, start, end, service_date, rule)
    logic.check_daily_limit(case, minutes, service_date, rule)              # tier 14

    return db.insert(
        "sessions",
        {
            "case_id": case["id"],
            "assignment_id": assignment["id"],
            "makeup_for_session_id": makeup_for["id"] if makeup_for else None,
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "scheduled_minutes": minutes,
            "service_date": service_date.isoformat(),
            "delivery_mode": session_mode,
            "subject": body["subject"],
            "status": "SCHEDULED",
            "outcome_reason": None,
            "actual_minutes": None,
            "credited_minutes": 0,
            "logged_by_user_id": None,
            "verified_by_user_id": None,
            "verified_at": None,
            "void_reason": None,
        },
    )


@bp.post("/hhi/sessions")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_session():
    body = middleware.body()
    start, end, minutes = _span(body)                              # tier 3

    case = db.get("cases", body["case_id"])                        # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    assignment = db.get("assignments", body["assignment_id"])
    if assignment is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")

    return middleware.obj(_schedule(case, assignment, body, start, end, minutes))


@bp.post("/hhi/sessions/<session_id>/makeup")
@endpoint(["CaseManager"], body=MAKEUP_BODY, status=201)
def create_makeup(session_id):
    body = middleware.body()
    start, end, minutes = _span(body)                              # tier 3

    missed = load_session(session_id)                              # tier 4
    assignment = db.get("assignments", body["assignment_id"])      # tier 5
    if assignment is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")

    case = db.get("cases", missed["case_id"])
    row = _schedule(case, assignment, body, start, end, minutes, makeup_for=missed)
    logic.recompute_makeup_obligation(case)
    return middleware.obj(row)


@bp.get("/hhi/sessions/<session_id>")
@endpoint(READ_ROLES)
def read_session(session_id):
    return middleware.obj(load_session(session_id))


@bp.get("/hhi/sessions")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_sessions():
    return listing("sessions", LIST_QUERY)


@bp.post("/hhi/sessions/<session_id>/log")
@endpoint(["HomeboundTeacher"], body=LOG_BODY)
def log_session(session_id):
    body = middleware.body()
    outcome = body["outcome"]

    if outcome == "DELIVERED":                                     # tier 3
        if body.get("actual_minutes") is None or body["actual_minutes"] < 1:
            fail("actual_minutes of at least 1 is required for a DELIVERED outcome.")
    if outcome == "STUDENT_UNAVAILABLE" and body.get("absence_kind") is None:
        fail("absence_kind is required for a STUDENT_UNAVAILABLE outcome.")

    session = load_session(session_id)                             # tier 4
    assignment = db.get("assignments", session["assignment_id"])
    if assignment.get("teacher_id") != middleware.user_id():       # tier 6
        raise ApiError("ERR_NOT_ASSIGNED_TEACHER")

    if session["status"] != "SCHEDULED":                           # tier 8
        raise ApiError("ERR_SESSION_ALREADY_LOGGED")
    case = db.get("cases", session["case_id"])
    if case["service_status"] not in IN_SERVICE:
        raise ApiError("ERR_CASE_NOT_ACTIVE")
    if clock.get_date() < parse_date(session["service_date"]):
        fail("The session cannot be logged before its service_date.")

    actor = middleware.user_id()
    db.set_field(session, "logged_by_user_id", actor)
    if "actual_minutes" in body:
        db.set_field(session, "actual_minutes", body["actual_minutes"])
    if "outcome_reason" in body:
        db.set_field(session, "outcome_reason", body["outcome_reason"])

    if outcome == "DELIVERED":
        rule = _rule_of(case)
        credited = logic.credited_minutes(
            body["actual_minutes"], session["delivery_mode"], rule
        )
        db.set_field(session, "status", "DELIVERED")
        db.set_field(session, "credited_minutes", credited)
        code = (
            "HB_VIRTUAL_PRESENT"
            if session["delivery_mode"] == "VIRTUAL_SYNC"
            else "HB_PRESENT"
        )
        logic.append_ledger_entry(case, session, code, credited, actor)
    else:
        db.set_field(session, "status", outcome)
        db.set_field(session, "credited_minutes", 0)
        if outcome == "STUDENT_UNAVAILABLE":
            code = (
                "HB_ABSENT_MEDICAL"
                if body["absence_kind"] == "MEDICAL"
                else "HB_ABSENT_UNEXCUSED"
            )
        else:
            code = "HB_NOT_SERVED"
        logic.append_ledger_entry(case, session, code, 0, actor)

    logic.recompute_reported_apportionment(case)
    logic.recompute_makeup_obligation(case)
    logic.recompute_service_gap(case)
    db.touch(case)
    return middleware.obj(session)


@bp.post("/hhi/sessions/<session_id>/verify")
@endpoint(["ProgramAdministrator", "CaseManager"])
def verify_session(session_id):
    session = load_session(session_id)
    if session["status"] != "DELIVERED":                            # tier 8
        raise ApiError("ERR_SESSION_NOT_DELIVERED")
    if session["verified_at"] is not None:
        raise ApiError("ERR_SESSION_ALREADY_VERIFIED")

    case = db.get("cases", session["case_id"])
    if middleware.user_id() == case["created_by_user_id"]:          # tier 9
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    db.set_field(session, "verified_at", clock.instant_str())
    db.set_field(session, "verified_by_user_id", middleware.user_id())
    return middleware.obj(session)


@bp.post("/hhi/sessions/<session_id>/void")
@endpoint(
    ["ProgramAdministrator"],
    body={"void_reason": {"type": "string", "required": True, "enum": VOID_REASONS}},
)
def void_session(session_id):
    session = load_session(session_id)
    if session["status"] != "DELIVERED":                            # tier 8
        raise ApiError("ERR_SESSION_NOT_DELIVERED")

    case = db.get("cases", session["case_id"])
    original = None
    for entry in logic.case_ledger(case):
        if entry["session_id"] == session["id"] and entry["attendance_code"] in (
            "HB_PRESENT",
            "HB_VIRTUAL_PRESENT",
        ):
            original = entry  # rows are ordered by created_at, so the last one wins

    db.set_field(session, "status", "VOIDED")
    db.set_field(session, "void_reason", middleware.body()["void_reason"])
    db.set_field(session, "credited_minutes", 0)
    db.set_field(session, "verified_at", None)
    db.set_field(session, "verified_by_user_id", None)

    logic.append_ledger_entry(
        case,
        session,
        "HB_REVERSAL",
        -1 * (original["apportionment_minutes"] if original else 0),
        middleware.user_id(),
        reversal_of_entry_id=original["id"] if original else None,
    )

    logic.recompute_reported_apportionment(case)
    logic.recompute_service_gap(case)
    db.touch(case)
    return middleware.obj(session)


@bp.post("/hhi/sessions/<session_id>/cancel")
@endpoint(["ProgramAdministrator"])
def cancel_session(session_id):
    session = load_session(session_id)
    if session["status"] != "SCHEDULED":                            # tier 8
        raise ApiError("ERR_SESSION_ALREADY_LOGGED")
    db.set_field(session, "status", "CANCELLED_ADMIN")
    return middleware.obj(session)
