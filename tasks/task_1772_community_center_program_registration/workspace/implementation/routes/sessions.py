"""ClassSession endpoints (PRD 3.2 / 3.3 / 3.9)."""
from flask import Blueprint, request

import clock
import services
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    check_int_range,
    get_or_404,
    list_response,
    new_record,
    opt_datetime,
    opt_int,
    req_datetime,
    req_int,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("sessions", __name__)

FIELDS = [
    "id",
    "program_id",
    "instructor_id",
    "title",
    "capacity",
    "min_enrollment",
    "fee_resident_cents",
    "fee_nonresident_cents",
    "enrollment_check_at",
    "enrolled_count",
    "waitlist_count",
    "status",
    "cancellation_reason",
    "created_at",
    "updated_at",
    "version",
]


def session_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/class-sessions", methods=["POST"])
def create_session():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    program_id = req_str(body, "program_id")
    instructor_id = req_str(body, "instructor_id")
    title = req_str(body, "title")
    capacity = req_int(body, "capacity")
    min_enrollment = req_int(body, "min_enrollment")
    fee_resident_cents = req_int(body, "fee_resident_cents")
    fee_nonresident_cents = req_int(body, "fee_nonresident_cents")
    enrollment_check_at = req_datetime(body, "enrollment_check_at")
    check_int_range(capacity, 1, None, "capacity")
    check_int_range(min_enrollment, 1, None, "min_enrollment")
    if min_enrollment > capacity:
        raise_err("ERR_INVALID_REQUEST", "min_enrollment must not exceed capacity")
    check_int_range(fee_resident_cents, 0, None, "fee_resident_cents")
    check_int_range(fee_nonresident_cents, 0, None, "fee_nonresident_cents")
    program = get_or_404(store.programs, program_id, "Program")
    get_or_404(store.instructors, instructor_id, "Instructor")
    season = store.seasons.get(program["season_id"])
    if season is not None and season["status"] == "CLOSED":
        raise_err("ERR_SEASON_CLOSED", "Season is CLOSED; new catalog content is rejected")
    rec = new_record()
    rec.update(
        program_id=program_id,
        instructor_id=instructor_id,
        title=title,
        capacity=capacity,
        min_enrollment=min_enrollment,
        fee_resident_cents=fee_resident_cents,
        fee_nonresident_cents=fee_nonresident_cents,
        enrollment_check_at=enrollment_check_at,
        enrolled_count=0,
        waitlist_count=0,
        status="DRAFT",
        cancellation_reason=None,
    )
    store.sessions[rec["id"]] = rec
    return success_object(session_out(rec), 201)


@bp.route("/class-sessions", methods=["GET"])
def list_sessions():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    program_id = request.args.get("program_id")
    instructor_id = request.args.get("instructor_id")
    status = request.args.get("status")
    records = list(store.sessions.values())
    if program_id is not None:
        records = [r for r in records if r["program_id"] == program_id]
    if instructor_id is not None:
        records = [r for r in records if r["instructor_id"] == instructor_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, session_out)


@bp.route("/class-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.sessions, session_id, "ClassSession")
    return success_object(session_out(rec), 200)


@bp.route("/class-sessions/<session_id>", methods=["PATCH"])
def patch_session(session_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    capacity = opt_int(body, "capacity", None)
    min_enrollment = opt_int(body, "min_enrollment", None)
    enrollment_check_at = opt_datetime(body, "enrollment_check_at")
    expected = req_int(body, "expected_class_session_version")
    if capacity is not None:
        check_int_range(capacity, 1, None, "capacity")
    if min_enrollment is not None:
        check_int_range(min_enrollment, 1, None, "min_enrollment")
    rec = get_or_404(store.sessions, session_id, "ClassSession")
    effective_capacity = capacity if capacity is not None else rec["capacity"]
    effective_min = min_enrollment if min_enrollment is not None else rec["min_enrollment"]
    if effective_min > effective_capacity:
        raise_err("ERR_INVALID_REQUEST", "min_enrollment must not exceed capacity")
    # Generic state legality first, then staleness, then the capacity floor (PRD 3.2).
    if rec["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err("ERR_INVALID_STATE", "Session can only be patched while DRAFT or PUBLISHED")
    if rec["version"] != expected:
        raise_err("ERR_STALE_VERSION", "expected_class_session_version does not match the current version")
    if effective_capacity < rec["enrolled_count"]:
        raise_err("ERR_CAPACITY_BELOW_ENROLLED", "capacity may not drop below enrolled_count")
    if capacity is not None:
        rec["capacity"] = capacity
    if min_enrollment is not None:
        rec["min_enrollment"] = min_enrollment
    if enrollment_check_at is not None:
        rec["enrollment_check_at"] = enrollment_check_at
    bump(rec)
    return success_object(session_out(rec), 200)


@bp.route("/class-sessions/<session_id>/publish", methods=["POST"])
def publish_session(session_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.sessions, session_id, "ClassSession")
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT session can be published")
    # Pinned precondition order (PRD 3.3): season -> contract -> meetings.
    season = services.season_of_session(rec)
    if season is None or season["status"] != "PUBLISHED":
        raise_err("ERR_SEASON_NOT_PUBLISHED", "The owning season must be PUBLISHED")
    accepted = any(
        c["session_id"] == rec["id"]
        and c["instructor_id"] == rec["instructor_id"]
        and c["status"] == "ACCEPTED"
        for c in store.contracts.values()
    )
    if not accepted:
        raise_err("ERR_CONTRACT_NOT_ACCEPTED", "An ACCEPTED contract for the session's instructor is required")
    if len(services.meetings_of_session(rec["id"])) == 0:
        raise_err("ERR_NO_MEETINGS", "Session must have at least one ClassMeeting")
    rec["status"] = "PUBLISHED"
    bump(rec)
    return success_object(session_out(rec), 200)


@bp.route("/class-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.sessions, session_id, "ClassSession")
    if rec["status"] not in ("PUBLISHED", "ACTIVE"):
        raise_err("ERR_INVALID_STATE", "Only a PUBLISHED or ACTIVE session can be cancelled")
    services.cancel_session_cascade(rec, "ADMIN")
    return success_object(session_out(rec), 200)


@bp.route("/class-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    rec = get_or_404(store.sessions, session_id, "ClassSession")
    if rec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Only an ACTIVE session can be completed")
    now = clock.now()
    for meeting in services.meetings_of_session(rec["id"]):
        if meeting["ends_at"] > now:
            raise_err("ERR_INVALID_STATE", "Every ClassMeeting must have ended before completion")
    services.complete_session_cascade(rec)
    return success_object(session_out(rec), 200)
