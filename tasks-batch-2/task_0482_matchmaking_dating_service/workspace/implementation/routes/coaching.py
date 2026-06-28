from flask import Blueprint

import errors
from db import db, new_id, iso_now_ms
from clock import clock
from middleware import authenticate, require_roles, require_member_owner
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, require_enum, stamp_create, touch,
    parse_pagination, paginate, sort_by_created, parse_iso,
)
from services.compute import serialize_coaching_session, coaching_suspended, reconcile_member
from services.calendar import session_overlaps_existing, session_violates_buffer

bp = Blueprint("coaching", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("ERR_MEMBER_NOT_FOUND")
    return m


def _get_session_or_404(session_id):
    s = db.coaching_sessions.get(session_id)
    if not s:
        raise errors.not_found("ERR_SESSION_NOT_FOUND")
    return s


@bp.route("/members/<member_id>/coaching-sessions", methods=["POST"])
def book_session(member_id):
    principal = authenticate()
    require_roles(principal, ("Matchmaker", "Member"))
    member = _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    body = get_json_body()
    coach_user_id = require_str(body, "coach_user_id")
    start_at = require_str(body, "start_at")
    end_at = require_str(body, "end_at")
    start_dt = parse_iso(start_at)
    end_dt = parse_iso(end_at)
    now = clock.now()
    if start_dt < now:
        raise errors.invalid_request("Session start_at must be >= clock now.")
    if end_dt <= start_dt:
        raise errors.invalid_request("Session end_at must be > start_at.")

    reconcile_member(member)

    # (8) calendar overlap + buffer
    if session_overlaps_existing(member_id, start_dt, end_dt):
        raise errors.conflict("ERR_DATE_OVERLAP")
    if session_violates_buffer(member_id, start_dt, end_dt):
        raise errors.conflict("ERR_COACHING_BUFFER_CONFLICT")

    # (10) coaching availability
    if coaching_suspended(member_id):
        raise errors.conflict("ERR_COACHING_SUSPENDED")

    sid = new_id()
    session = {
        "id": sid,
        "member_id": member_id,
        "coach_user_id": coach_user_id,
        "start_at": iso_now_ms(start_dt),
        "end_at": iso_now_ms(end_dt),
        "status": "BOOKED",
    }
    stamp_create(session)
    db.coaching_sessions[sid] = session
    return success_object(serialize_coaching_session(session), 201)


@bp.route("/members/<member_id>/coaching-sessions", methods=["GET"])
def list_sessions(member_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    limit, offset = parse_pagination()
    records = [s for s in db.coaching_sessions.values() if s["member_id"] == member_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_coaching_session(s) for s in page], limit, offset, total)


@bp.route("/coaching-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    s = _get_session_or_404(session_id)
    require_member_owner(principal, s["member_id"])
    return success_object(serialize_coaching_session(s))


@bp.route("/coaching-sessions/<session_id>/outcome", methods=["POST"])
def record_outcome(session_id):
    principal = authenticate()
    require_roles(principal, ("Matchmaker",))
    s = _get_session_or_404(session_id)
    body = get_json_body()
    outcome = require_enum(body, "outcome", ("HELD", "NO_SHOW"))
    if s["status"] != "BOOKED":
        raise errors.conflict("ERR_SESSION_NOT_BOOKED")
    now = clock.now()
    if now < parse_iso(s["start_at"]):
        # PRD: requires clock to have reached start_at; reuse not-started semantics
        raise errors.conflict("ERR_DATE_NOT_STARTED")
    if outcome == "HELD":
        s["status"] = "HELD"
        touch(s)
    else:
        s["status"] = "NO_SHOW"
        touch(s)
        # strike increment is observed via effective_strikes recomputation; the
        # NO_SHOW row itself is the source of truth. coaching_suspended is derived.
    return success_object(serialize_coaching_session(s))


@bp.route("/coaching-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    principal = authenticate()
    require_roles(principal, ("Member", "Matchmaker"))
    s = _get_session_or_404(session_id)
    require_member_owner(principal, s["member_id"])
    if s["status"] != "BOOKED":
        raise errors.conflict("ERR_SESSION_NOT_BOOKED")
    s["status"] = "CANCELLED"
    touch(s)
    return success_object(serialize_coaching_session(s))
