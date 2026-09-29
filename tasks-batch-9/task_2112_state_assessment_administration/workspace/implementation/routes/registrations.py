"""Student registrations, accommodation coding and review, attendance and
score recording (PRD 3.4, 3.6, 3.8)."""

from flask import Blueprint, request

import serialize
from db import create, db, ordered, touch
from derive import (
    ACCOMMODATION_CATALOG,
    live_registrations,
    recompute_seat_pressure,
    registrations_of_window,
    review_routing,
    seat_pressure_for,
    seats_required_for,
)
from errors import api_error
from middleware import (
    ALL_ROLES,
    DISTRICT_COORDINATOR,
    PROCTOR,
    SCHOOL_COORDINATOR,
    STATE_OFFICER,
    body_reference,
    endpoint,
    json_body,
    require_scope,
    resolve,
)
from response import object_response, paginate
from routes.sessions import required_phase
from validators import (
    enum_field,
    identifier_field,
    integer_field,
    nullable_identifier,
    nullable_string,
    optional_text,
    string_field,
    string_list_field,
)

bp = Blueprint("registrations", __name__)

STUDENT_STATE_ID_PATTERN = r"S[0-9]{8}"
ATTENDANCE_OUTCOMES = {"PRESENT", "ABSENT", "EXCUSED"}
DECISIONS = {"APPROVE", "REJECT"}
ACCEPTING_STATUSES = ("DRAFT", "SCHEDULED")
MAKEUP_ELIGIBLE_ATTENDANCE = ("ABSENT", "EXCUSED")


def _session_of(registration):
    return db.sessions.get(registration["session_id"])


def _school_of_session(session):
    return db.schools.get(session["school_id"]) if session else None


@bp.post("/registrations")
@endpoint(SCHOOL_COORDINATOR)
def create_registration(actor):
    # Check 4 — the acting school must own the session being seated.
    named_session = body_reference("session_id")
    scoped_session = db.sessions.get(named_session) if named_session else None
    if scoped_session is not None:
        require_scope(scoped_session["school_id"] == actor.user_id)

    body = json_body()
    session_id = identifier_field(body, "session_id")
    student_state_id = string_field(body, "student_state_id", pattern=STUDENT_STATE_ID_PATTERN)
    grade = integer_field(body, "grade", minimum=3, maximum=12)
    guardian_email = nullable_string(body, "guardian_email")
    makeup_of_registration_id = nullable_identifier(body, "makeup_of_registration_id")

    session = resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    original = None
    if makeup_of_registration_id is not None:
        original = resolve(db.registrations, makeup_of_registration_id, "ERR_REGISTRATION_NOT_FOUND")

    # Check 8 — the session's own status.
    if session["status"] not in ACCEPTING_STATUSES:
        raise api_error("ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS")

    # Check 9 — the governing window's phase.
    window = db.windows.get(session["window_id"])
    if window is None or window["status"] != required_phase(session["session_type"]):
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    if original is not None:
        original_session = _session_of(original)
        # Check 14 — segregation of duties is screened before eligibility.
        if (
            original_session is not None
            and original_session["proctor_id"] is not None
            and session["proctor_id"] is not None
            and original_session["proctor_id"] == session["proctor_id"]
        ):
            raise api_error("ERR_SEGREGATION_OF_DUTIES")

        # Check 15 — make-up linkage eligibility.
        eligible = (
            original["student_state_id"] == student_state_id
            and original_session is not None
            and original_session["window_id"] == session["window_id"]
            and (
                original["attendance_status"] in MAKEUP_ELIGIBLE_ATTENDANCE
                or original["score_status"] == "INVALIDATED"
            )
            and session["session_type"] == "MAKEUP"
        )
        if not eligible:
            raise api_error("ERR_MAKEUP_NOT_ELIGIBLE")

    # Check 22 — registration uniqueness on both axes.
    if makeup_of_registration_id is None:
        for existing in registrations_of_window(session["window_id"]):
            if (
                existing["student_state_id"] == student_state_id
                and existing["makeup_of_registration_id"] is None
                and existing["attendance_status"] != "WITHDRAWN"
            ):
                raise api_error(
                    "ERR_DUPLICATE_REGISTRATION",
                    "the student already holds an initial registration in this window.",
                )
    else:
        for existing in db.registrations.values():
            if existing["makeup_of_registration_id"] == makeup_of_registration_id:
                raise api_error(
                    "ERR_DUPLICATE_REGISTRATION",
                    "the original registration already has a make-up seat.",
                )

    # Check 23 — seat capacity after applying the request.
    prospective = live_registrations(session["id"]) + [
        {"accommodation_codes": [], "seats_required": 1}
    ]
    pressure = seat_pressure_for(session, prospective)
    if pressure["seats_consumed"] > pressure["effective_seat_capacity"]:
        raise api_error("ERR_SESSION_CAPACITY_EXCEEDED")

    registration = create(
        db.registrations,
        {
            "session_id": session_id,
            "makeup_of_registration_id": makeup_of_registration_id,
            "student_state_id": student_state_id,
            "grade": grade,
            "guardian_email": guardian_email,
            "accommodation_codes": [],
            "accommodation_status": "NONE",
            "accommodation_decision_note": None,
            "attendance_status": "PENDING",
            "raw_score": None,
            "score_status": "NOT_SCORED",
            "report_delivery_status": "NOT_QUEUED",
            "report_suppressed_reason": None,
            "report_delivered_at": None,
            "seats_required": 1,
        },
    )
    recompute_seat_pressure(session)
    return object_response(serialize.registration(registration), 201)


@bp.get("/registrations/<registration_id>")
@endpoint(*ALL_ROLES)
def read_registration(actor, registration_id):
    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")
    return object_response(serialize.registration(registration))


@bp.get("/registrations")
@endpoint(*ALL_ROLES)
def list_registrations(actor):
    session_id = request.args.get("session_id")
    student_state_id = request.args.get("student_state_id")
    makeup_of_registration_id = request.args.get("makeup_of_registration_id")
    attendance_status = request.args.get("attendance_status")
    score_status = request.args.get("score_status")
    items = [
        registration
        for registration in db.registrations.values()
        if (session_id is None or registration["session_id"] == session_id)
        and (student_state_id is None or registration["student_state_id"] == student_state_id)
        and (
            makeup_of_registration_id is None
            or registration["makeup_of_registration_id"] == makeup_of_registration_id
        )
        and (attendance_status is None or registration["attendance_status"] == attendance_status)
        and (score_status is None or registration["score_status"] == score_status)
    ]
    return paginate(ordered(items), serialize.registration)


# --------------------------------------------------------------------------
# Accommodations
# --------------------------------------------------------------------------
@bp.post("/registrations/<registration_id>/accommodation-codings")
@endpoint(SCHOOL_COORDINATOR)
def code_accommodations(actor, registration_id):
    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")
    session = _session_of(registration)
    require_scope(session is not None and session["school_id"] == actor.user_id)

    body = json_body()
    codes = string_list_field(
        body, "accommodation_codes", set(ACCOMMODATION_CATALOG), max_entries=5
    )

    if session["status"] not in ACCEPTING_STATUSES:
        raise api_error("ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS")

    # Check 23 — the whole request is rejected when the room would overflow.
    seats_required = seats_required_for(codes)
    prospective = []
    for candidate in live_registrations(session["id"]):
        if candidate["id"] == registration["id"]:
            prospective.append(
                {"accommodation_codes": codes, "seats_required": seats_required}
            )
        else:
            prospective.append(candidate)
    pressure = seat_pressure_for(session, prospective)
    if pressure["seats_consumed"] > pressure["effective_seat_capacity"]:
        raise api_error("ERR_SESSION_CAPACITY_EXCEEDED")

    registration["accommodation_codes"] = list(codes)
    registration["accommodation_status"] = review_routing(codes)
    registration["seats_required"] = seats_required
    touch(registration)
    recompute_seat_pressure(session)
    return object_response(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/accommodation-decisions")
@endpoint(DISTRICT_COORDINATOR)
def decide_accommodations(actor, registration_id):
    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")
    session = _session_of(registration)
    school = _school_of_session(session)
    require_scope(school is not None and school["district_id"] == actor.user_id)

    body = json_body()
    decision = enum_field(body, "decision", DECISIONS)
    note = optional_text(body, "note")

    if registration["accommodation_status"] != "REQUESTED":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "no accommodation package awaits review.")

    registration["accommodation_status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    registration["accommodation_decision_note"] = note
    touch(registration)
    return object_response(serialize.registration(registration))


# --------------------------------------------------------------------------
# Attendance and scores
# --------------------------------------------------------------------------
@bp.post("/registrations/<registration_id>/attendance")
@endpoint(PROCTOR)
def record_attendance(actor, registration_id):
    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")
    session = _session_of(registration)
    require_scope(session is not None and session["proctor_id"] == actor.user_id)

    body = json_body()
    attendance_status = enum_field(body, "attendance_status", ATTENDANCE_OUTCOMES)

    if session["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the session is not active.")
    if registration["attendance_status"] != "PENDING":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "attendance has already been settled.")

    registration["attendance_status"] = attendance_status
    touch(registration)
    return object_response(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/scores")
@endpoint(STATE_OFFICER)
def record_score(actor, registration_id):
    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")
    session = _session_of(registration)

    body = json_body()
    raw_score = integer_field(body, "raw_score", minimum=0, maximum=100)

    # Check 8 — the registration's own state dimensions.
    if registration["score_status"] != "NOT_SCORED":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the registration has already been scored.")
    if registration["attendance_status"] != "PRESENT":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the student did not sit the test.")

    # Check 9 — the governing window's phase.
    window = db.windows.get(session["window_id"]) if session else None
    if window is None or window["status"] != "SCORING":
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    if session["status"] != "CLOSED":
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the owning session is not closed.")

    registration["raw_score"] = raw_score
    registration["score_status"] = "SCORED"
    touch(registration)
    return object_response(serialize.registration(registration))
