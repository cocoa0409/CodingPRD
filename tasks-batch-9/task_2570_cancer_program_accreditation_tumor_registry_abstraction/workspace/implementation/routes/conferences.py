"""Multidisciplinary cancer conference calendar, attendance and credit."""

from datetime import timedelta

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import all_of, clock_date, clock_now, fmt_date, fmt_instant, mark, parse_instant
from errors import ApiError, invalid
from middleware import ANY_ROLE, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("conferences", __name__)

BUFFER = timedelta(minutes=spec.CONFERENCE_BUFFER_MINUTES)


def _rescore(session):
    mark(session)
    session["prospective_case_ratio"] = calcs.prospective_ratio(
        session.get("prospective_case_count") or 0,
        session.get("cases_presented_count") or 0)
    session["quorum_met"] = calcs.quorum_met(session)


@bp.post(PREFIX + "/conference-sessions")
@endpoint(["AccreditationCoordinator", "RegistryManager"])
def create_session():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    start_at = validate.f_instant(body, "start_at")
    end_at = validate.f_instant(body, "end_at")
    required_disciplines = validate.f_enum_list(body, "required_disciplines",
                                                spec.DISCIPLINES)
    if end_at <= start_at:
        raise invalid("end_at must be strictly later than start_at.")

    need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    for existing in services.sessions_of_program(program_id):
        other_start = parse_instant(existing["start_at"])
        other_end = parse_instant(existing["end_at"])
        if other_start is None or other_end is None:
            continue
        if start_at < other_end + BUFFER and other_start < end_at + BUFFER:
            raise ApiError("ERR_CONFERENCE_SLOT_CONFLICT")

    session = db.new_entity("session", {
        "program_id": program_id,
        "start_at": fmt_instant(start_at),
        "end_at": fmt_instant(end_at),
        "required_disciplines": list(required_disciplines),
        "attendances": [],
        "cases_presented_count": 0,
        "prospective_case_count": 0,
        "prospective_case_ratio": 0.0,
        "quorum_met": False,
        "session_state": "SCHEDULED",
        "credited_on": None,
    })
    return ok(session, 201)


@bp.get(PREFIX + "/conference-sessions")
@endpoint(ANY_ROLE)
def list_sessions():
    program_id = validate.q_str("program_id")
    session_state = validate.q_enum("session_state", spec.SESSION_STATES)
    items = all_of("session")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if session_state is not None:
        items = [s for s in items if s["session_state"] == session_state]
    return page(items)


@bp.get(PREFIX + "/conference-sessions/<session_id>")
@endpoint(ANY_ROLE)
def read_session(session_id):
    session = need("session", session_id, "ERR_SESSION_NOT_FOUND")
    return ok(session)


@bp.post(PREFIX + "/conference-sessions/<session_id>/attendances")
@endpoint(["AccreditationCoordinator"])
def record_attendance(session_id):
    body = validate.body()
    attendee_ref = validate.f_str(body, "attendee_ref")
    discipline = validate.f_enum(body, "discipline", spec.DISCIPLINES)
    attended_minutes = validate.f_int(body, "attended_minutes", minimum=0)
    is_required_coordinator = validate.f_bool(body, "is_required_coordinator",
                                              required=False, default=False)

    session = need("session", session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED")
    for att in session["attendances"]:
        if att.get("attendee_ref") == attendee_ref:
            raise ApiError("ERR_DUPLICATE_ATTENDANCE")

    mark(session)
    session["attendances"] = session["attendances"] + [{
        "attendee_ref": attendee_ref,
        "discipline": discipline,
        "is_required_coordinator": is_required_coordinator,
        "attended_minutes": attended_minutes,
    }]
    _rescore(session)
    return ok(session)


@bp.post(PREFIX + "/conference-sessions/<session_id>/hold")
@endpoint(["AccreditationCoordinator"])
def hold_session(session_id):
    body = validate.body()
    cases_presented_count = validate.f_int(body, "cases_presented_count",
                                           minimum=0)
    prospective_case_count = validate.f_int(body, "prospective_case_count",
                                            minimum=0)
    if prospective_case_count > cases_presented_count:
        raise invalid("prospective_case_count may not exceed "
                      "cases_presented_count.")

    session = need("session", session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED")
    start_at = parse_instant(session["start_at"])
    if start_at is not None and clock_now() < start_at:
        raise ApiError("ERR_SESSION_NOT_YET_STARTED")

    mark(session)
    session["cases_presented_count"] = cases_presented_count
    session["prospective_case_count"] = prospective_case_count
    session["session_state"] = "HELD"
    _rescore(session)
    return ok(session)


@bp.post(PREFIX + "/conference-sessions/<session_id>/credit")
@endpoint(["AccreditationCoordinator"])
def credit_session(session_id):
    body = validate.body()
    disposition = validate.f_enum(body, "disposition", spec.SESSION_DISPOSITIONS)
    validate.f_str(body, "credit_note", required=False)

    session = need("session", session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] != "HELD":
        raise ApiError("ERR_SESSION_NOT_HELD")
    if disposition == "CREDIT" and not session["quorum_met"]:
        raise ApiError("ERR_CONFERENCE_QUORUM_NOT_MET")

    mark(session)
    if disposition == "CREDIT":
        session["session_state"] = "CREDITED"
        session["credited_on"] = fmt_date(clock_date())
    else:
        session["session_state"] = "NOT_CREDITED"
        session["credited_on"] = None

    program = db.get("program", session["program_id"])
    if program is not None:
        services.refresh_program_conference(program)
    return ok(session)
