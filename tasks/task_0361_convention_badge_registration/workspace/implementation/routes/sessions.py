"""Session and SessionReservation endpoints (PRD §3.6)."""
from flask import Blueprint, request

import common
import db
import errors
import util
from middleware import authenticate, authorize
from services import calc, lookup, state
import response

bp = Blueprint("sessions", __name__)

ALL_READ = {"ConventionAdmin", "RegistrationAgent", "Attendee"}


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
@bp.route("/conventions/<cid>/sessions", methods=["POST"])
def create_session(cid):
    _, role = authenticate()
    authorize(role, {"ConventionAdmin"})
    conv = lookup.convention(cid)
    body = common.get_body()

    title = common.require_str(body, "title")
    start = common.require_datetime(body, "start_utc")
    end = common.require_datetime(body, "end_utc")
    if end <= start:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")
    seat_capacity = common.require_int(body, "seat_capacity", minimum=1)
    requires_vip = common.optional_bool(body, "requires_vip", False)

    row = common.common_fields()
    row.update({
        "convention_id": conv["id"],
        "title": title,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "seat_capacity": seat_capacity,
        "seats_taken": 0,
        "requires_vip": requires_vip,
    })
    db.sessions[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/conventions/<cid>/sessions", methods=["GET"])
def list_sessions(cid):
    _, role = authenticate()
    authorize(role, ALL_READ)
    conv = lookup.convention(cid)
    rows = [s for s in db.sessions.values() if s["convention_id"] == conv["id"]]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role = authenticate()
    authorize(role, ALL_READ)
    s = lookup.session(sid)
    return response.success(common.serialize(s), 200)


# --------------------------------------------------------------------------- #
# SessionReservation
# --------------------------------------------------------------------------- #
@bp.route("/session-reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    authorize(role, {"Attendee", "RegistrationAgent"})
    body = common.get_body()

    # Existence: body FKs left-to-right (PRD §2.8).
    session_id = common.require_str(body, "session_id")
    badge_id = common.require_str(body, "badge_id")
    session = lookup.session(session_id)
    badge = lookup.badge(badge_id)

    # Ownership: Attendee reserves only for a badge it holds (PRD §2.1).
    lookup.require_attendee_owns(role, user_id, badge["holder_attendee_id"])

    # Banned check on the holder attendee (PRD §2.9 step 4).
    holder = db.attendees.get(badge["holder_attendee_id"])
    if holder is not None and holder["status"] == "BANNED":
        raise errors.err(errors.ERR_ATTENDEE_BANNED, "Attendee is banned")

    sess_start = util.parse_iso(session["start_utc"])
    sess_end = util.parse_iso(session["end_utc"])

    # (8) session time-conflict: badge must not already hold a CONFIRMED
    # reservation whose half-open [start,end) overlaps this session (PRD §3.6).
    for res in db.session_reservations.values():
        if res["badge_id"] != badge_id or res["status"] != "CONFIRMED":
            continue
        other = db.sessions.get(res["session_id"])
        if other is None:
            continue
        o_start = util.parse_iso(other["start_utc"])
        o_end = util.parse_iso(other["end_utc"])
        # Half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b. Abutting allowed.
        if sess_start < o_end and o_start < sess_end:
            raise errors.err(errors.ERR_SESSION_TIME_CONFLICT, "Badge already has an overlapping reservation")

    # (9) VIP requirement (PRD §3.6).
    if session["requires_vip"]:
        tier = db.ticket_types[badge["ticket_type_id"]]["tier"]
        if tier != "VIP":
            raise errors.err(errors.ERR_VIP_REQUIRED, "Session requires a VIP badge")

    confirmed_only = common.optional_bool(body, "confirmed_only", False)
    seat_free = session["seats_taken"] < session["seat_capacity"]

    # (16) confirmed_only + no free seat -> ERR_SESSION_FULL (PRD §3.6).
    if confirmed_only and not seat_free:
        raise errors.err(errors.ERR_SESSION_FULL, "No free seat and confirmed_only requested")

    # (17) OCC against Session.version (PRD §2.7). Mismatch (412) outranks the
    # generic well-formedness check; a missing field falls through to (18) below.
    expected = body.get("expected_session_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != session["version"]:
            raise errors.err(errors.ERR_STALE_SESSION_VERSION, "Stale session version")
    else:
        # (18) well-formedness: required field absent or non-integer.
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_session_version is required")

    # --- create ---
    row = common.common_fields()
    if seat_free:
        status = "CONFIRMED"
        score = 0
    else:
        status = "WAITLISTED"
        # waitlist_score via priority-scoring with group_size defaulting to 1 (PRD §3.6).
        conv = db.conventions[session["convention_id"]]
        created_dt = util.parse_iso(row["created_at"])
        lottery_open = util.parse_iso(conv["lottery_open_utc"])
        score = calc.priority_score(holder["loyalty_tier"], created_dt, lottery_open, 1)

    row.update({
        "session_id": session_id,
        "badge_id": badge_id,
        "status": status,
        "waitlist_score": score,
    })
    db.session_reservations[row["id"]] = row

    if status == "CONFIRMED":
        # seats_taken increment + Session.version bump (PRD §3.6).
        state.recompute_session_seats(session)
    return response.success(common.serialize(row), 201)


@bp.route("/session-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    user_id, role = authenticate()
    authorize(role, ALL_READ)
    res = lookup.session_reservation(rid)
    badge = db.badges.get(res["badge_id"])
    if badge is not None:
        lookup.require_attendee_owns(role, user_id, badge["holder_attendee_id"])
    return response.success(common.serialize(res), 200)


@bp.route("/session-reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    authorize(role, ALL_READ)
    rows = list(db.session_reservations.values())
    session_filter = request.args.get("session_id")
    badge_filter = request.args.get("badge_id")
    if session_filter is not None:
        rows = [r for r in rows if r["session_id"] == session_filter]
    if badge_filter is not None:
        rows = [r for r in rows if r["badge_id"] == badge_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/session-reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = authenticate()
    authorize(role, {"Attendee", "RegistrationAgent"})
    res = lookup.session_reservation(rid)
    badge = db.badges.get(res["badge_id"])
    if badge is not None:
        lookup.require_attendee_owns(role, user_id, badge["holder_attendee_id"])

    if res["status"] not in {"CONFIRMED", "WAITLISTED"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation cannot be cancelled from its current state")

    was_confirmed = res["status"] == "CONFIRMED"
    res["status"] = "CANCELLED"
    common.touch(res)

    if was_confirmed:
        session = db.sessions[res["session_id"]]
        # Decrement seats_taken, then promote top waitlisted (cascade C) — PRD §3.6.
        state.recompute_session_seats(session)
        state.promote_waitlist(session)

    return response.success(common.serialize(res), 200)
