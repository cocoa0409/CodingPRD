"""Tool memberships, stand sessions, and monthly billing (PRD §3.12)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import (make_common, touch, paginate, sorted_by_created,
                           parse_month_param, PER_SESSION_CENTS,
                           PER_SESSION_MONTHLY_CAP, FLAT_MONTHLY_CENTS)

bp = Blueprint("memberships", __name__)

TIERS = ["BASIC", "PRO"]


def membership_view(m):
    return {
        "id": m["id"],
        "member_name": m["member_name"],
        "member_email": m["member_email"],
        "tier": m["tier"],
        "status": m["status"],
        "start_date": m["start_date"],
        "end_date": m["end_date"],
        "suspended_reason": m["suspended_reason"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def session_view(s):
    return {
        "id": s["id"],
        "membership_id": s["membership_id"],
        "stand_number": s["stand_number"],
        "start_time": s["start_time"],
        "end_time": s["end_time"],
        "status": s["status"],
        "started_at": s["started_at"],
        "closed_at": s["closed_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _get_membership(membership_id):
    m = db.memberships.get(membership_id)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", f"ToolMembership {membership_id} does not exist")
    return m


def _get_session(session_id):
    s = db.tool_sessions.get(session_id)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", f"ToolSession {session_id} does not exist")
    return s


def _check_member_ownership(role, user_id, membership_id):
    if role == "Member" and user_id != membership_id:
        raise ApiError("ERR_FORBIDDEN", "Members may only act on their own membership")


@bp.post("/memberships")
def create_membership():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "member_name": {"type": "string", "required": True},
        "member_email": {"type": "string", "required": True},
        "tier": {"type": "string", "required": True, "enum": TIERS},
        "end_date": {"type": "string", "required": True},
    })
    try:
        _parse_iso(body["end_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "end_date must be a YYYY-MM-DD calendar date")
    m = make_common()
    m.update({
        "member_name": body["member_name"],
        "member_email": body["member_email"],
        "tier": body["tier"],
        "status": "ACTIVE",
        "start_date": db.today().isoformat(),
        "end_date": body["end_date"],
        "suspended_reason": None,
    })
    db.memberships[m["id"]] = m
    return success(membership_view(m), status=201)


@bp.get("/memberships/<membership_id>")
def get_membership(membership_id):
    user_id, role = require_roles("ShopCoordinator", "ProgramDirector", "Member")
    m = _get_membership(membership_id)
    _check_member_ownership(role, user_id, membership_id)
    return success(membership_view(m))


@bp.get("/memberships")
def list_memberships():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.memberships.values())
    for param in ("status", "tier"):
        value = request.args.get(param)
        if value is not None:
            rows = [m for m in rows if m[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([membership_view(m) for m in page], pagination=pg)


@bp.post("/memberships/<membership_id>/suspend")
def suspend_membership(membership_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"reason": {"type": "string"}})
    m = _get_membership(membership_id)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE membership can be suspended")
    m["status"] = "SUSPENDED"
    m["suspended_reason"] = body.get("reason")
    touch(m)
    return success(membership_view(m))


@bp.post("/memberships/<membership_id>/reinstate")
def reinstate_membership(membership_id):
    require_roles("ShopCoordinator")
    m = _get_membership(membership_id)
    if m["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED membership can be reinstated")
    m["status"] = "ACTIVE"
    touch(m)
    return success(membership_view(m))


@bp.get("/memberships/<membership_id>/billing")
def membership_billing(membership_id):
    user_id, role = require_roles("ShopCoordinator", "ProgramDirector", "Member")
    m = _get_membership(membership_id)
    _check_member_ownership(role, user_id, membership_id)
    raw_month = request.args.get("month")
    if raw_month is None:
        year, month = db.now().year, db.now().month
    else:
        year, month = parse_month_param(raw_month)
    month_start = _month_start(year, month)
    if month == 12:
        month_end = _month_start(year + 1, 1)
    else:
        month_end = _month_start(year, month + 1)
    billable = [
        s for s in db.tool_sessions.values()
        if s["membership_id"] == m["id"]
        and s["status"] in ("IN_USE", "CLOSED")
        and month_start <= _parse_iso(s["start_time"]) < month_end
    ]
    if m["tier"] == "BASIC":
        amount = min(len(billable) * PER_SESSION_CENTS, PER_SESSION_MONTHLY_CAP)
    else:
        amount = FLAT_MONTHLY_CENTS
    return success({
        "membership_id": m["id"],
        "month": f"{year:04d}-{month:02d}",
        "tier": m["tier"],
        "session_count": len(billable),
        "amount_cents": amount,
    })


def _month_start(year, month):
    from datetime import datetime, timezone
    return datetime(year, month, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Stand sessions
# ---------------------------------------------------------------------------

@bp.post("/memberships/<membership_id>/sessions")
def create_session(membership_id):
    user_id, role = require_roles("ShopCoordinator", "Member")
    body = get_body()
    validate_payload(body, {
        "stand_number": {"type": "integer", "required": True},
        "start_time": {"type": "string", "required": True},
        "end_time": {"type": "string", "required": True},
    })
    m = _get_membership(membership_id)
    _check_member_ownership(role, user_id, membership_id)
    try:
        start = _parse_iso(body["start_time"])
        end = _parse_iso(body["end_time"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "start_time/end_time must be ISO-8601 instants")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", "Membership must be ACTIVE")
    if body["stand_number"] < 1 or body["stand_number"] > 4:
        raise ApiError("ERR_STAND_NUMBER_INVALID", "stand_number must be within 1..4")
    duration_min = (end - start).total_seconds() / 60
    if duration_min < 30 or duration_min > 180:
        raise ApiError("ERR_SESSION_DURATION_INVALID", "Session duration must be 30..180 minutes")
    # 15-minute cleanup buffer per stand against every BOOKED/IN_USE session.
    buffer = timedelta(minutes=15)
    for other in db.tool_sessions.values():
        if other["stand_number"] != body["stand_number"] or other["status"] not in ("BOOKED", "IN_USE"):
            continue
        o_start = _parse_iso(other["start_time"])
        o_end = _parse_iso(other["end_time"])
        if not (start >= o_end + buffer or end + buffer <= o_start):
            raise ApiError("ERR_STAND_BUFFER_CONFLICT", "Stand booking violates the 15-minute buffer")

    s = make_common()
    s.update({
        "membership_id": m["id"],
        "stand_number": body["stand_number"],
        "start_time": body["start_time"],
        "end_time": body["end_time"],
        "status": "BOOKED",
        "started_at": None,
        "closed_at": None,
    })
    db.tool_sessions[s["id"]] = s
    return success(session_view(s), status=201)


@bp.get("/sessions/<session_id>")
def get_tool_session(session_id):
    user_id, role = require_roles("ShopCoordinator", "ProgramDirector", "Member")
    s = _get_session(session_id)
    _check_member_ownership(role, user_id, s["membership_id"])
    return success(session_view(s))


@bp.get("/sessions")
def list_tool_sessions():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.tool_sessions.values())
    for param in ("membership_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s[param] == value]
    stand = request.args.get("stand_number")
    if stand is not None:
        try:
            stand_num = int(stand)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "stand_number must be an integer")
        rows = [s for s in rows if s["stand_number"] == stand_num]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([session_view(s) for s in page], pagination=pg)


@bp.post("/sessions/<session_id>/start")
def start_session(session_id):
    user_id, _ = require_roles("Member")
    s = _get_session(session_id)
    if s["membership_id"] != user_id:
        raise ApiError("ERR_MEMBER_NOT_OWNER", "Members may only start their own sessions")
    m = db.memberships.get(s["membership_id"])
    if m is None:
        raise ApiError("ERR_NOT_FOUND", f"ToolMembership {s['membership_id']} does not exist")
    if s["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Only a BOOKED session can be started")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", "Membership must be ACTIVE")
    if db.now() < _parse_iso(s["start_time"]) - timedelta(minutes=10):
        raise ApiError("ERR_START_TOO_EARLY", "Session cannot start before start_time - 10m")
    s["status"] = "IN_USE"
    s["started_at"] = db.now_iso()
    touch(s)
    return success(session_view(s))


@bp.post("/sessions/<session_id>/close")
def close_session(session_id):
    user_id, role = require_roles("ShopCoordinator", "Member")
    s = _get_session(session_id)
    if role == "Member" and s["membership_id"] != user_id:
        raise ApiError("ERR_MEMBER_NOT_OWNER", "Members may only close their own sessions")
    if s["status"] != "IN_USE":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_USE session can be closed")
    s["status"] = "CLOSED"
    s["closed_at"] = db.now_iso()
    touch(s)
    return success(session_view(s))


@bp.post("/sessions/<session_id>/cancel")
def cancel_session(session_id):
    user_id, role = require_roles("ShopCoordinator", "Member")
    s = _get_session(session_id)
    if role == "Member" and s["membership_id"] != user_id:
        raise ApiError("ERR_MEMBER_NOT_OWNER", "Members may only cancel their own sessions")
    if s["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Only a BOOKED session can be cancelled")
    s["status"] = "CANCELLED"
    touch(s)
    return success(session_view(s))
