"""Playtest session endpoints: schedule/assign/reschedule/start/complete/cancel."""

from datetime import timedelta

import db
from db import _parse_iso, _format_iso
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_int, require_enum, require_datetime,
    stamp_new, touch, validate_window,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_STALE_VERSION, ERR_STATION_REQUIRED,
    ERR_STATION_CONFLICT, ERR_MODERATOR_CONFLICT, ERR_MODERATOR_REQUIRED,
    ERR_STUDY_NOT_CLOSED, ERR_SESSION_NOT_IN_WINDOW,
)
from services.serializers import public
from services.cascade import recompute_strikes, cancel_booking_cascade

bp = make_blueprint("sessions")

MODERATOR_BUFFER = timedelta(minutes=15)


def _get_session(sid):
    s = db.sessions.get(sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "Session not found")
    return s


def _station_conflict(station_id, starts_at, ends_at, exclude_session_id=None):
    """Half-open overlap: conflict iff new.starts < ex.ends AND ex.starts < new.ends."""
    for s in db.sessions.values():
        if s["station_id"] != station_id:
            continue
        if s["id"] == exclude_session_id:
            continue
        if s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        ex_start = _parse_iso(s["starts_at"])
        ex_end = _parse_iso(s["ends_at"])
        if starts_at < ex_end and ex_start < ends_at:
            return True
    return False


def _moderator_conflict(moderator_id, starts_at, ends_at, exclude_session_id=None):
    """15-minute buffered overlap: conflict iff new.starts < ex.ends+15 AND ex.starts < new.ends+15."""
    for s in db.sessions.values():
        if s.get("moderator_id") != moderator_id:
            continue
        if s["id"] == exclude_session_id:
            continue
        if s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        ex_start = _parse_iso(s["starts_at"])
        ex_end = _parse_iso(s["ends_at"])
        if starts_at < ex_end + MODERATOR_BUFFER and ex_start < ends_at + MODERATOR_BUFFER:
            return True
    return False


@bp.route("/playtests/sessions", methods=["POST"])
def create_session():
    require_roles("Researcher")
    body = get_payload()
    study_id = require_string(body, "study_id")
    mode = require_enum(body, "mode", ("REMOTE", "IN_LAB"))
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    seat_capacity = require_int(body, "seat_capacity", minimum=1)
    station_id = body.get("station_id")
    if station_id is not None and not isinstance(station_id, str):
        raise_error(ERR_INVALID_REQUEST, "station_id must be a string")

    # Window rule: ends_at must be strictly after starts_at -> ERR_WINDOW_VIOLATION
    validate_window(starts_at, ends_at)

    # Existence: study, then station (when supplied)
    study = db.studies.get(study_id)
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    station = None
    if station_id is not None:
        station = db.lab_stations.get(station_id)
        if station is None:
            raise_error(ERR_NOT_FOUND, "Lab station not found")

    # State gate: study must be RECRUITING / CLOSED / ANALYSIS
    if study["status"] not in ("RECRUITING", "CLOSED", "ANALYSIS"):
        raise_error(ERR_INVALID_STATE, "Study must be RECRUITING, CLOSED, or ANALYSIS")

    # Station requirement rules
    if mode == "IN_LAB":
        if station_id is None:
            raise_error(ERR_STATION_REQUIRED, "IN_LAB session requires station_id")
        if station["status"] != "AVAILABLE":
            raise_error(ERR_STATION_REQUIRED, "Station is not AVAILABLE")
    else:  # REMOTE
        if station_id is not None:
            raise_error(ERR_STATION_REQUIRED, "REMOTE session must not carry a station_id")

    # Temporal rule: station half-open overlap
    if mode == "IN_LAB" and _station_conflict(station_id, starts_at, ends_at):
        raise_error(ERR_STATION_CONFLICT, "Station is double-booked for that window")

    rec = {
        "study_id": study_id,
        "mode": mode,
        "station_id": station_id if mode == "IN_LAB" else None,
        "moderator_id": None,
        "starts_at": _format_iso(starts_at),
        "ends_at": _format_iso(ends_at),
        "seat_capacity": seat_capacity,
        "seats_taken": 0,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    db.sessions[rec["id"]] = rec
    return success(public(rec, "session"), status=201)


@bp.route("/playtests/sessions", methods=["GET"])
def list_sessions():
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant", "IncentiveOfficer")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.sessions.values())
    for param in ("study_id", "moderator_id", "station_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(s, "session") for s in page], status=200, pagination=pagination)


@bp.route("/playtests/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant", "IncentiveOfficer")
    s = _get_session(sid)
    return success(public(s, "session"), status=200)


@bp.route("/playtests/sessions/<sid>/assign-moderator", methods=["POST"])
def assign_moderator(sid):
    require_roles("Researcher")
    s = _get_session(sid)
    body = get_payload()
    moderator_id = require_string(body, "moderator_id")
    moderator = db.moderators.get(moderator_id)
    if moderator is None:
        raise_error(ERR_NOT_FOUND, "Moderator not found")
    if s["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Session must be SCHEDULED to assign a moderator")
    if moderator["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Moderator must be ACTIVE to be assigned")
    starts_at = _parse_iso(s["starts_at"])
    ends_at = _parse_iso(s["ends_at"])
    if _moderator_conflict(moderator_id, starts_at, ends_at, exclude_session_id=s["id"]):
        raise_error(ERR_MODERATOR_CONFLICT, "Moderator has a conflicting session")
    s["moderator_id"] = moderator_id
    touch(s)
    return success(public(s, "session"), status=200)


@bp.route("/playtests/sessions/<sid>/reschedule", methods=["PATCH"])
def reschedule_session(sid):
    require_roles("Researcher")
    s = _get_session(sid)
    body = get_payload()

    if "expected_session_version" not in body or body["expected_session_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "expected_session_version is required")
    expected = body["expected_session_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_session_version must be an integer")
    if expected != s["version"]:
        raise_error(ERR_STALE_VERSION, "Session version mismatch")

    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    validate_window(starts_at, ends_at)

    if s["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Session must be SCHEDULED to reschedule")

    # Re-run station half-open and moderator buffered conflict checks for the new window
    if s["mode"] == "IN_LAB" and s.get("station_id"):
        if _station_conflict(s["station_id"], starts_at, ends_at, exclude_session_id=s["id"]):
            raise_error(ERR_STATION_CONFLICT, "Station is double-booked for that window")
    if s.get("moderator_id"):
        if _moderator_conflict(s["moderator_id"], starts_at, ends_at, exclude_session_id=s["id"]):
            raise_error(ERR_MODERATOR_CONFLICT, "Moderator has a conflicting session")

    s["starts_at"] = _format_iso(starts_at)
    s["ends_at"] = _format_iso(ends_at)
    touch(s)
    return success(public(s, "session"), status=200)


@bp.route("/playtests/sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    user_id, _role = require_roles("Moderator")
    s = _get_session(sid)
    if s["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Session must be SCHEDULED to start")
    if not s.get("moderator_id"):
        raise_error(ERR_MODERATOR_REQUIRED, "Session has no assigned moderator")
    if user_id != s["moderator_id"]:
        raise_error(ERR_FORBIDDEN, "Only the assigned moderator may start the session")
    study = db.studies.get(s["study_id"])
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    if study["status"] not in ("CLOSED", "ANALYSIS"):
        raise_error(ERR_STUDY_NOT_CLOSED, "Study must be CLOSED or ANALYSIS to start sessions")
    now = db.clock.now()
    if not (_parse_iso(s["starts_at"]) <= now <= _parse_iso(s["ends_at"])):
        raise_error(ERR_SESSION_NOT_IN_WINDOW, "Current time is outside the session window")
    s["status"] = "IN_PROGRESS"
    touch(s)
    return success(public(s, "session"), status=200)


@bp.route("/playtests/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    user_id, _role = require_roles("Moderator")
    s = _get_session(sid)
    if s["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "Session must be IN_PROGRESS to complete")
    if user_id != s.get("moderator_id"):
        raise_error(ERR_FORBIDDEN, "Only the assigned moderator may complete the session")

    s["status"] = "COMPLETED"
    touch(s)

    # Auto no-show: every booking still in BOOKED / PROMOTED -> NO_SHOW
    pending = [
        b for b in db.bookings.values()
        if b["session_id"] == s["id"] and b["status"] in ("BOOKED", "PROMOTED")
    ]
    pending.sort(key=lambda b: (b["_created_sort"], b["_seq"]))
    now_iso = db.clock.now_iso()
    affected_participants = []
    for b in pending:
        b["status"] = "NO_SHOW"
        b["no_show_recorded_at"] = now_iso
        touch(b)
        affected_participants.append(b["participant_id"])
    # Recompute strikes per affected participant (may trigger auto-suspension)
    for pid in affected_participants:
        participant = db.participants.get(pid)
        if participant is not None:
            recompute_strikes(participant)
    return success(public(s, "session"), status=200)


@bp.route("/playtests/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    require_roles("Researcher", "ResearchOpsAdmin")
    s = _get_session(sid)
    if s["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Session must be SCHEDULED to cancel")
    s["status"] = "CANCELLED"
    touch(s)
    # Cancel every booking in BOOKED / PROMOTED / WAITLISTED with NO promotion
    for b in list(db.bookings.values()):
        if b["session_id"] == s["id"] and b["status"] in ("BOOKED", "PROMOTED", "WAITLISTED"):
            b["status"] = "CANCELLED"
            touch(b)
    s["seats_taken"] = 0
    touch(s)
    return success(public(s, "session"), status=200)
