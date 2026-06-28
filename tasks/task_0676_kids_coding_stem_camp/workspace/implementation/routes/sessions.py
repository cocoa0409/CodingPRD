"""Session routes & lifecycle (PRD §3.4), plus the camp quote (PRD §3.6)."""
from flask import Blueprint

import errors
from errors import err
from clock import clock
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import (
    get_body, require_int, require_enum, parse_datetime, parse_iso,
    parse_pagination, invalid,
)
from services import lookup
from services.capacity import derive_posture
from services.pricing import camp_block_quote
from routes.common import arg, paginate

bp = Blueprint("sessions", __name__)

FORMATS = {"AFTER_SCHOOL", "WEEKLY", "CAMP"}


@bp.route("/sessions", methods=["POST"])
def create_session():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    center_id = body.get("center_id")
    lookup.require_center(center_id)
    program_id = body.get("program_id")
    lookup.require_program(program_id)

    fmt = require_enum(body, "format", FORMATS)
    week_count = require_int(body, "week_count", minimum=1)
    starts_at = parse_datetime(body, "starts_at")
    ends_at = parse_datetime(body, "ends_at")
    device_seats = require_int(body, "device_seats_requested", minimum=1)
    instructors = require_int(body, "assigned_instructor_count", minimum=1)
    if ends_at <= starts_at:
        raise invalid("ends_at must be strictly after starts_at.")
    if fmt == "CAMP":
        if week_count <= 1:
            raise invalid("CAMP sessions must have week_count > 1.")
    else:
        if week_count != 1:
            raise invalid("week_count must equal 1 unless format is CAMP.")
    rec = db.make({
        "center_id": center_id,
        "program_id": program_id,
        "format": fmt,
        "week_count": week_count,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "device_seats_requested": device_seats,
        "assigned_instructor_count": instructors,
        "status": "DRAFT",
        "confirmed_seat_count": 0,
    })
    db.sessions[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/sessions/<rid>", methods=["GET"])
def get_session(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_session(rid)
    return success(out(rec))


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    center_id = arg("center_id")
    program_id = arg("program_id")
    status = arg("status")
    items = [s for s in db.sessions.values()
             if (center_id is None or s["center_id"] == center_id)
             and (program_id is None or s["program_id"] == program_id)
             and (status is None or s["status"] == status)]
    return paginate(items, limit, offset)


@bp.route("/sessions/<rid>/quote", methods=["GET", "POST"])
def quote_session(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    session = lookup.require_session(rid)
    program = db.programs[session["program_id"]]
    # member_ids supplied in body (or query). Each must exist.
    body = get_body()
    member_ids = body.get("member_ids")
    if member_ids is None:
        # On a GET the client sends a list as repeated query params
        # (?member_ids=a&member_ids=b); read all of them.
        from flask import request
        repeated = request.args.getlist("member_ids")
        if repeated:
            member_ids = repeated
        else:
            raw = arg("member_ids")
            member_ids = raw.split(",") if raw else None
    if not isinstance(member_ids, list) or not member_ids:
        raise invalid("member_ids must be a non-empty list.")
    members = []
    for mid in member_ids:
        member = lookup.require_member(mid)
        if member["program_id"] != session["program_id"]:
            raise err(errors.ERR_PROGRAM_MISMATCH, "Member not on session program.")
        members.append(member)
    block_total, per_seat = camp_block_quote(program, session, members)
    data = out(session)
    data["block_total_cents"] = block_total
    data["per_seat"] = per_seat
    return success(data)


@bp.route("/sessions/<rid>/open", methods=["POST"])
def open_session(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    session = lookup.require_session(rid)
    if session["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Session is not DRAFT.")
    # preconditions: ends_at strictly after starts_at; assigned_instructor_count >= 1
    starts_at = parse_iso(session["starts_at"])
    ends_at = parse_iso(session["ends_at"])
    if ends_at <= starts_at or session["assigned_instructor_count"] < 1:
        raise err(errors.ERR_INVALID_STATE, "Session cannot be opened.")
    session["confirmed_seat_count"] = 0
    session["status"] = "OPEN"
    derive_posture(session)  # cap may already be empty band etc.
    db.touch(session)
    return success(out(session))


@bp.route("/sessions/<rid>/complete", methods=["POST"])
def complete_session(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    session = lookup.require_session(rid)
    if session["status"] not in ("OPEN", "RESTRICTED", "FULL"):
        raise err(errors.ERR_INVALID_STATE, "Session cannot be completed from its current state.")
    ends_at = parse_iso(session["ends_at"])
    if clock.now() < ends_at:
        raise err(errors.ERR_SESSION_NOT_ENDED, "Session has not ended yet.")
    for e in db.enrollments.values():
        if e["session_id"] != session["id"]:
            continue
        if e["attendance_status"] == "CHECKED_IN":
            e["attendance_status"] = "ATTENDED"
            db.touch(e)
        elif e["attendance_status"] == "RESERVED":
            e["attendance_status"] = "NO_SHOW"
            if e["billing_status"] == "CHARGED":
                e["billing_status"] = "FORFEITED"
            # COVERED membership seat is NOT returned.
            db.touch(e)
    session["status"] = "COMPLETED"
    db.touch(session)
    return success(out(session))


@bp.route("/sessions/<rid>/cancel", methods=["POST"])
def cancel_session(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    session = lookup.require_session(rid)
    if session["status"] not in ("DRAFT", "OPEN", "RESTRICTED", "FULL"):
        raise err(errors.ERR_INVALID_STATE, "Session cannot be cancelled from its current state.")
    # HOP 1: drive every non-terminal enrollment to CANCELLED with full refund.
    for e in db.enrollments.values():
        if e["session_id"] != session["id"]:
            continue
        if e["attendance_status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        e["attendance_status"] = "CANCELLED"
        # HOP 2: settle billing as REFUNDED (full refund regardless of window).
        e["billing_status"] = "REFUNDED"
        if e["coverage"] == "DROP_IN":
            member = db.members.get(e["member_id"])
            guardian = db.guardians.get(member["guardian_id"]) if member else None
            if guardian is not None:
                refund = e["price_cents"] + e["wallet_applied_cents"]
                if refund:
                    guardian["wallet_credit_cents"] += refund
                    db.touch(guardian)  # HOP 3: wallet now observable
        else:  # MEMBERSHIP
            _return_membership_seat(e)
        db.touch(e)
    # confirmed_seat_count drops to 0 (all non-terminal seats cancelled).
    session["confirmed_seat_count"] = sum(
        1 for x in db.enrollments.values()
        if x["session_id"] == session["id"]
        and x["attendance_status"] in ("RESERVED", "CHECKED_IN", "ATTENDED")
    )
    session["status"] = "CANCELLED"
    db.touch(session)
    return success(out(session))


def _return_membership_seat(enrollment):
    """Decrement sessions_used_this_cycle on the member's covering ACTIVE/any
    membership. We track the covering membership id on the enrollment."""
    mid = enrollment.get("membership_id")
    if mid is None:
        return
    membership = db.memberships.get(mid)
    if membership is None:
        return
    if membership["sessions_used_this_cycle"] > 0:
        membership["sessions_used_this_cycle"] -= 1
        db.touch(membership)
