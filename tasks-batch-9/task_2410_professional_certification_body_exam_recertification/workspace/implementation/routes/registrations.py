"""ExamRegistration endpoints: seats, sittings, scoring (PRD 3.7 / 3.8 / 3.10)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CANDIDATE,
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    ROLE_PSYCHOMETRICIAN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_int,
    present,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import calc, cascades, derive, lookup
from util import add_days, add_minutes

bp = Blueprint("registrations", __name__)

CONSUMING = derive.CONSUMING_SEAT_STATUSES
HOLDING_SEAT_STATUSES = ("SCHEDULED", "CHECKED_IN", "COMPLETED")


def _consumed_registrations(application):
    return [r for r in derive.registrations_of_application(application["id"])
            if r["seat_status"] in CONSUMING]


@bp.post("/exam-registrations")
@api
def create_registration():
    actor = authenticate([ROLE_CANDIDATE, ROLE_EXAM_OPERATIONS])
    raw = peek_body()
    payload = raw or {}

    # Layer 4: the application and the form resolve before anything else.
    application = lookup.application(payload.get("application_id"))
    form = lookup.form(payload.get("form_id"))

    # Layer 5: a Candidate-role caller registers only for themselves.
    if actor.role == ROLE_CANDIDATE and application["candidate_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    body = ensure_body(raw)
    fee_paid_cents = req_int(body, "fee_paid_cents", minimum=0)

    program = DB.programs[application["program_id"]]
    # Layer 13.  PRD 3.1: an application already APPROVED under a program that has
    # since been superseded remains usable for registration, so supersession alone
    # does not close the door.
    if program["status"] not in ("ACTIVE", "SUPERSEDED"):
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

    # Layer 14.
    if form["status"] != "PUBLISHED":
        raise ApiError("ERR_FORM_NOT_PUBLISHED")

    # Layer 15.
    if application["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_NOT_APPROVED")

    candidate = DB.candidates[application["candidate_id"]]
    # Layer 20.
    if candidate["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_BARRED")

    # Layer 26.
    if form["program_id"] != application["program_id"]:
        raise ApiError("ERR_ELIGIBILITY_PROGRAM_MISMATCH")

    # Layer 31.
    expires = application["eligibility_expires_on"]
    if expires is not None and DB.now() > expires:
        raise ApiError("ERR_ELIGIBILITY_EXPIRED")

    consumed = _consumed_registrations(application)

    # Layer 32: the retake wait since the latest consumed attempt.
    sittings = [r["session_ends_at"] for r in consumed if r["session_ends_at"] is not None]
    if sittings:
        last_sitting = max(sittings)
        if DB.now() < add_days(last_sitting, program["retake_wait_days"]):
            raise ApiError("ERR_RETAKE_WAIT_ACTIVE")

    # Layer 38: the attempt ceiling.
    if len(consumed) >= program["max_attempts_per_cycle"]:
        raise ApiError("ERR_MAX_ATTEMPTS_REACHED")

    # Layer 44.
    if fee_paid_cents < program["exam_fee_cents"]:
        raise ApiError("ERR_EXAM_FEE_INSUFFICIENT")

    registration = new_record(
        candidate_id=application["candidate_id"],
        application_id=application["id"],
        form_id=form["id"],
        session_id=None,
        session_ends_at=None,
        fee_paid_cents=fee_paid_cents,
        attempt_number=len(consumed) + 1,
        eligibility_expires_on_snapshot=application["eligibility_expires_on"],
        seat_status="UNSCHEDULED",
        score_status="NOT_APPLICABLE",
        score_status_before_hold=None,
        raw_score=None,
        scaled_score=None,
        outcome=None,
        form_reassignment_required=False,
    )
    mark_created(registration)
    DB.registrations[registration["id"]] = registration
    return created_response(serialize.registration(registration))


@bp.get("/exam-registrations/<registration_id>")
@api
def read_registration(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_CANDIDATE, ROLE_PROGRAM_ADMIN,
                  ROLE_PSYCHOMETRICIAN])
    return object_response(serialize.registration(lookup.registration(registration_id)))


@bp.get("/exam-registrations")
@api
def list_registrations():
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_CANDIDATE, ROLE_PROGRAM_ADMIN,
                  ROLE_PSYCHOMETRICIAN])
    limit, offset = read_pagination()
    rows = ordered(DB.registrations.values())
    rows = apply_filters(rows, {
        "candidate_id": "candidate_id",
        "application_id": "application_id",
        "form_id": "form_id",
        "session_id": "session_id",
        "seat_status": "seat_status",
        "score_status": "score_status",
        "outcome": "outcome",
    })
    return paginate(rows, serialize.registration, limit, offset)


def _own_registration(actor, registration):
    """Layer 5 for the two seat actions."""
    if actor.role == ROLE_CANDIDATE and registration["candidate_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def _buffered_conflict(new_session, other_session):
    """PRD 3.7: both comparisons are inclusive, so a 119-minute gap is refused."""
    buffer_minutes = calc.CANDIDATE_WINDOW_BUFFER_MINUTES
    return (
        add_minutes(new_session["starts_at"], -buffer_minutes) <= other_session["ends_at"]
        and add_minutes(other_session["starts_at"], -buffer_minutes) <= new_session["ends_at"]
    )


@bp.post("/exam-registrations/<registration_id>/schedule")
@api
def schedule_registration(registration_id):
    actor = authenticate([ROLE_CANDIDATE, ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    raw = peek_body()

    # Layer 4.
    session = lookup.session((raw or {}).get("session_id"))

    # Layer 5.
    _own_registration(actor, registration)

    body = ensure_body(raw)
    expected_session_version = req_int(body, "expected_session_version", minimum=0)

    # Layer 11.
    if expected_session_version != session["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Layer 12.
    if registration["seat_status"] != "UNSCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    form = DB.forms[registration["form_id"]]
    # Layer 14.
    if form["status"] != "PUBLISHED":
        raise ApiError("ERR_FORM_NOT_PUBLISHED")

    candidate = DB.candidates[registration["candidate_id"]]
    # Layer 20.
    if candidate["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_BARRED")

    # Layer 28: the buffered candidate-window collision.
    for sibling in derive.registrations_of_candidate(candidate["id"]):
        if sibling["id"] == registration["id"]:
            continue
        if sibling["seat_status"] not in HOLDING_SEAT_STATUSES:
            continue
        held = sibling["session_id"]
        if not held or held not in DB.sessions:
            continue
        if _buffered_conflict(session, DB.sessions[held]):
            raise ApiError("ERR_CANDIDATE_WINDOW_CONFLICT")

    # Layer 29.
    if DB.now() >= session["starts_at"]:
        raise ApiError("ERR_SESSION_CLOSED")

    # Layer 46.
    if derive.session_seats_reserved(session) >= session["seat_capacity"]:
        raise ApiError("ERR_SESSION_FULL")

    registration["seat_status"] = "SCHEDULED"
    registration["session_id"] = session["id"]
    registration["session_ends_at"] = session["ends_at"]
    touch(registration)
    derive.recount_session(session)
    return object_response(serialize.registration(registration))


@bp.post("/exam-registrations/<registration_id>/cancel-schedule")
@api
def cancel_schedule(registration_id):
    actor = authenticate([ROLE_CANDIDATE, ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    _own_registration(actor, registration)
    body = ensure_body(peek_body())
    opt_str(body, "cancel_reason")

    # Layer 12.
    if registration["seat_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    held = registration["session_id"]
    session = DB.sessions.get(held) if held else None
    # Layer 29.
    if session is not None and DB.now() >= session["starts_at"]:
        raise ApiError("ERR_SESSION_CLOSED")

    registration["seat_status"] = "UNSCHEDULED"
    registration["session_id"] = None
    # session_ends_at is deliberately retained for the retake-wait arithmetic.
    touch(registration)
    if session is not None:
        derive.recount_session(session)
    return object_response(serialize.registration(registration))


@bp.post("/exam-registrations/<registration_id>/check-in")
@api
def check_in(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    body = ensure_body(peek_body())
    opt_str(body, "checkin_note")

    # Layer 12.
    if registration["seat_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    form = DB.forms[registration["form_id"]]
    # Layer 14.
    if form["status"] != "PUBLISHED":
        raise ApiError("ERR_FORM_NOT_PUBLISHED")

    candidate = DB.candidates[registration["candidate_id"]]
    # Layer 20.
    if candidate["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_BARRED")

    # Layer 30: the window opens 30 minutes before the start and closes at the end.
    session = DB.sessions.get(registration["session_id"])
    if session is None:
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED")
    opens_at = add_minutes(session["starts_at"], -calc.CHECKIN_LEAD_MINUTES)
    if not opens_at <= DB.now() <= session["ends_at"]:
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED")

    registration["seat_status"] = "CHECKED_IN"
    registration["score_status"] = "PENDING"
    touch(registration)
    return object_response(serialize.registration(registration))


@bp.post("/exam-registrations/<registration_id>/submit-responses")
@api
def submit_responses(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    body = ensure_body(peek_body())
    if not present(body, "raw_score"):
        raise ApiError("ERR_INVALID_REQUEST")
    raw_score = req_int(body, "raw_score", minimum=None)

    # Layer 12: both dimensions must be in the state the transition declares.
    if registration["seat_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE")
    if registration["score_status"] not in ("PENDING", "WITHHELD"):
        raise ApiError("ERR_INVALID_STATE")

    # Layer 21.
    if registration["score_status"] == "WITHHELD":
        raise ApiError("ERR_SCORE_UNDER_SECURITY_HOLD")

    form = DB.forms[registration["form_id"]]
    total = form["scored_item_count"]
    # Layer 41.
    if raw_score < 0 or raw_score > total:
        raise ApiError("ERR_RAW_SCORE_OUT_OF_RANGE")

    cut = form["raw_cut_score"]
    if cut is None:
        raise ApiError("ERR_INVALID_STATE")

    scaled_score, outcome = calc.scaled_score_equating(raw_score, cut, total)
    registration["raw_score"] = raw_score
    registration["scaled_score"] = scaled_score
    registration["outcome"] = outcome
    registration["seat_status"] = "COMPLETED"
    registration["score_status"] = "SCORED"
    touch(registration)

    # The owning application's attempts_consumed is derived from this seat status.
    application = DB.applications.get(registration["application_id"])
    if application is not None:
        touch(application)
    return object_response(serialize.registration(registration))


@bp.post("/exam-registrations/<registration_id>/report-score")
@api
def report_score(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    body = ensure_body(peek_body())
    opt_str(body, "report_note")

    # Layer 12.
    if registration["score_status"] != "SCORED":
        raise ApiError("ERR_INVALID_STATE")

    # Layer 21: an unresolved incident blocks release whatever its severity.
    for incident in derive.incidents_of_registration(registration["id"]):
        if incident["status"] == "OPEN":
            raise ApiError("ERR_SCORE_UNDER_SECURITY_HOLD")

    registration["score_status"] = "REPORTED"
    touch(registration)

    if registration["outcome"] == "PASS":
        application = DB.applications[registration["application_id"]]
        program = DB.programs[application["program_id"]]
        certificant, cycle = cascades.pending_reexam_cycle(registration["candidate_id"])
        if cycle is not None:
            cycle["reexam_registration_id"] = registration["id"]
            cycle["status"] = "SATISFIED"
            touch(cycle)
            derive.refresh_certificant_projection(certificant)
        else:
            cascades.mint_certificant(registration, application, program)

    return object_response(serialize.registration(registration))
