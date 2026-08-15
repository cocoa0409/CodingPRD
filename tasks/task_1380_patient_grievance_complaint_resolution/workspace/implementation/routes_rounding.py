"""Routes: patient-relations rounding sessions."""

from flask import Blueprint, g, request

import db
import errors
import middleware
from clock import iso_ms, parse_iso
from helpers import (
    check_datetime,
    check_string,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_rounding,
    sorted_by_creation,
    stamp_new,
    touch,
)
from response import success_list, success_object
from state import CLOCK

bp = Blueprint("rounding", __name__)


def get_rounding_or_404(session_id):
    session = db.rounding_sessions.get(session_id)
    if session is None:
        raise errors.not_found(errors.ERR_ROUNDING_NOT_FOUND, "RoundingSession not found")
    return session


@bp.route("/api/rounding-sessions", methods=["POST"])
def create_rounding_session():
    middleware.authenticate()
    middleware.require_roles("PatientAdvocate")
    body = get_body()
    require_present(body, "unit_id", "start_at", "end_at")
    unit = db.hospital_units.get(body.get("unit_id"))
    if unit is None:
        raise errors.not_found(errors.ERR_UNIT_NOT_FOUND, "HospitalUnit not found")
    # The session's advocate is the caller's own staff identity.
    advocate = db.staff_members.get(g.user_id)
    # Staff availability (rung 8): an advocate on leave may not schedule.
    if advocate is not None and advocate["on_leave"]:
        raise errors.api_error(
            errors.ERR_ADVOCATE_ON_LEAVE,
            403,
            "Staff member on_leave may not create rounding sessions",
        )
    start_dt = check_datetime(body, "start_at", required=True)
    end_dt = check_datetime(body, "end_at", required=True)
    # Occupancy (rung 10): advocate pairwise overlap (half-open intervals,
    # adjacency allowed), then unit aggregate capacity.
    for other in db.rounding_sessions.values():
        if other["advocate_id"] != g.user_id or other["status"] != "SCHEDULED":
            continue
        other_start = parse_iso(other["start_at"])
        other_end = parse_iso(other["end_at"])
        if start_dt < other_end and other_start < end_dt:
            raise errors.api_error(
                errors.ERR_ROUNDING_OVERLAP,
                409,
                "Advocate has another SCHEDULED session whose window overlaps",
            )
    concurrent = 0
    for other in db.rounding_sessions.values():
        if other["unit_id"] != unit["id"] or other["status"] != "SCHEDULED":
            continue
        other_start = parse_iso(other["start_at"])
        other_end = parse_iso(other["end_at"])
        if start_dt < other_end and other_start < end_dt:
            concurrent += 1
    if concurrent >= unit["max_concurrent_roundings"]:
        raise errors.api_error(
            errors.ERR_UNIT_ROUNDING_CAPACITY,
            409,
            "Unit already at max_concurrent_roundings overlapping sessions",
        )
    # Temporal sanity (rung 11).
    now = CLOCK.now()
    if end_dt <= start_dt or start_dt < now:
        raise errors.api_error(
            errors.ERR_ROUNDING_WINDOW_INVALID,
            422,
            "Rounding window end_at <= start_at or start_at before now",
        )
    session = stamp_new()
    session.update(
        {
            "unit_id": unit["id"],
            "advocate_id": g.user_id,
            "start_at": iso_ms(start_dt),
            "end_at": iso_ms(end_dt),
            "status": "SCHEDULED",
            "outcome_note": None,
        }
    )
    db.rounding_sessions[session["id"]] = session
    return success_object(serialize_rounding(session), 201)


@bp.route("/api/rounding-sessions", methods=["GET"])
def list_rounding_sessions():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    unit_id = request.args.get("unit_id")
    advocate_id = request.args.get("advocate_id")
    status = request.args.get("status")
    sessions = list(db.rounding_sessions.values())
    if unit_id is not None:
        sessions = [s for s in sessions if s["unit_id"] == unit_id]
    if advocate_id is not None:
        sessions = [s for s in sessions if s["advocate_id"] == advocate_id]
    if status is not None:
        sessions = [s for s in sessions if s["status"] == status]
    sessions = sorted_by_creation(sessions)
    page, total = paginate(sessions, limit, offset)
    return success_list([serialize_rounding(s) for s in page], limit, offset, total)


@bp.route("/api/rounding-sessions/<session_id>", methods=["GET"])
def get_rounding_session(session_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    session = get_rounding_or_404(session_id)
    return success_object(serialize_rounding(session))


@bp.route("/api/rounding-sessions/<session_id>/complete", methods=["POST"])
def complete_rounding_session(session_id):
    middleware.authenticate()
    middleware.require_roles("PatientAdvocate")
    body = get_body()
    session = get_rounding_or_404(session_id)
    if session["advocate_id"] != g.user_id:
        raise errors.identity_mismatch("Caller is not the session's advocate")
    if session["status"] != "SCHEDULED":
        raise errors.api_error(
            errors.ERR_ROUNDING_INVALID_STATE, 409, "Session is not SCHEDULED"
        )
    outcome_note = body.get("outcome_note")
    if outcome_note is not None and not isinstance(outcome_note, str):
        raise errors.invalid_request("outcome_note must be a string")
    session["status"] = "COMPLETED"
    if outcome_note is not None:
        session["outcome_note"] = outcome_note
    touch(session)
    return success_object(serialize_rounding(session))


@bp.route("/api/rounding-sessions/<session_id>/cancel", methods=["POST"])
def cancel_rounding_session(session_id):
    middleware.authenticate()
    middleware.require_roles("PatientAdvocate")
    get_body()
    session = get_rounding_or_404(session_id)
    if session["advocate_id"] != g.user_id:
        raise errors.identity_mismatch("Caller is not the session's advocate")
    if session["status"] != "SCHEDULED":
        raise errors.api_error(
            errors.ERR_ROUNDING_INVALID_STATE, 409, "Session is not SCHEDULED"
        )
    session["status"] = "CANCELLED"
    touch(session)
    return success_object(serialize_rounding(session))
