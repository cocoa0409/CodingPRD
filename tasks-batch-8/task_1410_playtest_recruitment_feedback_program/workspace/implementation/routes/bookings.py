"""Session booking endpoints: book/cancel/mark-attended/mark-no-show."""

import db
from db import _parse_iso, _format_iso
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_SESSION_NOT_BOOKABLE, ERR_NOT_ENROLLED, ERR_DUPLICATE_BOOKING,
    ERR_PARTICIPANT_CONFLICT,
)
from services.serializers import public
from services.cascade import cancel_booking_cascade, recompute_strikes

bp = make_blueprint("bookings")


def _get_booking(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise_error(ERR_NOT_FOUND, "Booking not found")
    return b


def _participant_conflict(participant_id, starts_at, ends_at):
    """Closed-interval overlap: touching endpoints DO conflict."""
    for b in db.bookings.values():
        if b["participant_id"] != participant_id:
            continue
        if b["status"] not in ("BOOKED", "PROMOTED"):
            continue
        session = db.sessions.get(b["session_id"])
        if session is None:
            continue
        ex_start = _parse_iso(session["starts_at"])
        ex_end = _parse_iso(session["ends_at"])
        if starts_at <= ex_end and ex_start <= ends_at:
            return True
    return False


@bp.route("/playtests/session-bookings", methods=["POST"])
def create_booking():
    user_id, _role = require_roles("Participant")
    body = get_payload()
    session_id = require_string(body, "session_id")
    session = db.sessions.get(session_id)
    if session is None:
        raise_error(ERR_NOT_FOUND, "Session not found")
    participant = db.participants.get(user_id)
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    # State: session must be SCHEDULED
    if session["status"] != "SCHEDULED":
        raise_error(ERR_SESSION_NOT_BOOKABLE, "Session is not SCHEDULED")

    # Referential: participant must hold an ENROLLED application in the session's study
    enrolled = any(
        a for a in db.applications.values()
        if a["study_id"] == session["study_id"]
        and a["participant_id"] == participant["id"]
        and a["status"] == "ENROLLED"
    )
    if not enrolled:
        raise_error(ERR_NOT_ENROLLED, "No ENROLLED application for this study")

    # Uniqueness: one non-terminal booking per (session, participant)
    for b in db.bookings.values():
        if (b["session_id"] == session["id"] and b["participant_id"] == participant["id"]
                and b["status"] in ("BOOKED", "WAITLISTED", "PROMOTED")):
            raise_error(ERR_DUPLICATE_BOOKING,
                        "A non-terminal booking already exists for this session and participant")

    # Temporal: participant closed-interval overlap check
    starts_at = _parse_iso(session["starts_at"])
    ends_at = _parse_iso(session["ends_at"])
    if _participant_conflict(participant["id"], starts_at, ends_at):
        raise_error(ERR_PARTICIPANT_CONFLICT, "Participant has a conflicting booking")

    # Seat gate evaluated BEFORE insert
    if session.get("seats_taken", 0) < session["seat_capacity"]:
        status = "BOOKED"
    else:
        status = "WAITLISTED"

    rec = {
        "session_id": session["id"],
        "participant_id": participant["id"],
        "status": status,
        "no_show_recorded_at": None,
    }
    stamp_new(rec)
    db.bookings[rec["id"]] = rec
    if status == "BOOKED":
        session["seats_taken"] = session.get("seats_taken", 0) + 1
        touch(session)
    return success(public(rec, "booking"), status=201)


@bp.route("/playtests/session-bookings", methods=["GET"])
def list_bookings():
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.bookings.values())
    for param in ("session_id", "participant_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if str(b.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(b, "booking") for b in page], status=200, pagination=pagination)


@bp.route("/playtests/session-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant")
    b = _get_booking(bid)
    return success(public(b, "booking"), status=200)


@bp.route("/playtests/session-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = require_roles("Participant", "ResearchOpsAdmin")
    b = _get_booking(bid)
    if role == "Participant" and user_id != b["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the owning participant may cancel this booking")
    if b["status"] not in ("BOOKED", "PROMOTED", "WAITLISTED"):
        raise_error(ERR_INVALID_STATE, "Booking must be BOOKED, PROMOTED, or WAITLISTED to cancel")
    cancel_booking_cascade(b, promote=True)
    return success(public(b, "booking"), status=200)


@bp.route("/playtests/session-bookings/<bid>/mark-attended", methods=["POST"])
def mark_attended(bid):
    user_id, _role = require_roles("Moderator")
    b = _get_booking(bid)
    session = db.sessions.get(b["session_id"])
    if session is None:
        raise_error(ERR_NOT_FOUND, "Session not found")
    if b["status"] not in ("BOOKED", "PROMOTED"):
        raise_error(ERR_INVALID_STATE, "Booking must be BOOKED or PROMOTED")
    if session["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "Session must be IN_PROGRESS")
    if user_id != session.get("moderator_id"):
        raise_error(ERR_FORBIDDEN, "Only the assigned moderator may mark attendance")
    b["status"] = "ATTENDED"
    touch(b)
    return success(public(b, "booking"), status=200)


@bp.route("/playtests/session-bookings/<bid>/mark-no-show", methods=["POST"])
def mark_no_show(bid):
    user_id, _role = require_roles("Moderator")
    b = _get_booking(bid)
    session = db.sessions.get(b["session_id"])
    if session is None:
        raise_error(ERR_NOT_FOUND, "Session not found")
    if b["status"] not in ("BOOKED", "PROMOTED"):
        raise_error(ERR_INVALID_STATE, "Booking must be BOOKED or PROMOTED")
    if session["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "Session must be IN_PROGRESS")
    if user_id != session.get("moderator_id"):
        raise_error(ERR_FORBIDDEN, "Only the assigned moderator may mark a no-show")
    b["status"] = "NO_SHOW"
    b["no_show_recorded_at"] = db.clock.now_iso()
    touch(b)
    participant = db.participants.get(b["participant_id"])
    if participant is not None:
        recompute_strikes(participant)
    return success(public(b, "booking"), status=200)
