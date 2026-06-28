"""WaitlistEntry endpoints (PRD §3.6)."""
from flask import Blueprint, request

from clock import clock
from constants import ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR
from db import db, stamp_new, touch
from errors import (
    err, ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE, ERR_MEMBER_SUSPENDED,
    ERR_WAITLIST_FULL, ERR_SESSION_NOT_FULL, ERR_NOT_FOUND,
)
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import waitlist_out
from services import lookup, validate, paging, booking

bp = Blueprint("waitlist", __name__)

READ_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR}


@bp.route("/studios/<studio_id>/sessions/<session_id>/waitlist", methods=["POST"])
def join_waitlist(studio_id, session_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_MEMBER})
    session = lookup.get_session_in_studio(studio_id, session_id)
    body = validate.get_body()
    member_id = validate.require_str(body, "member_id")
    credit_pack_id = validate.require_str(body, "credit_pack_id")

    member = lookup.get_member(member_id)
    if user_id != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only join the waitlist for themselves")

    # session must be SCHEDULED
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED")

    # suspended member barred
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_SUSPENDED, "Suspended members cannot join the waitlist")

    # pre-authorized pack must exist and belong to the member
    pack = lookup.get_pack(credit_pack_id)
    if pack["member_id"] != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Pack does not belong to the member")

    # joining is meaningful only for a full session
    if booking.booked_count(session_id) < session["capacity"]:
        raise err(ERR_SESSION_NOT_FULL, "Session still has free capacity; book instead")

    # waitlist capacity
    if booking.waiting_count(session_id) >= session["waitlist_capacity"]:
        raise err(ERR_WAITLIST_FULL, "Waitlist is full")

    rec = {
        "session_id": session_id,
        "member_id": member_id,
        "credit_pack_id": credit_pack_id,
        "enqueued_at": clock.now(),
        "status": "WAITING",
        "promoted_reservation_id": None,
    }
    stamp_new(rec)
    db.waitlist_entries[rec["id"]] = rec
    touch(session)  # waitlist_count recompute (derived) -> session mutation
    return success_object(waitlist_out(rec), 201)


@bp.route("/waitlist-entries/<entry_id>", methods=["GET"])
def get_waitlist_entry(entry_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_waitlist_entry(entry_id)
    if role == ROLE_MEMBER and user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own waitlist entries")
    return success_object(waitlist_out(rec), 200)


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = paging.get_pagination()
    f_session = request.args.get("session_id")
    f_member = request.args.get("member_id")
    f_pack = request.args.get("credit_pack_id")
    f_promoted = request.args.get("promoted_reservation_id")
    records = []
    for w in db.waitlist_entries.values():
        if f_session is not None and w["session_id"] != f_session:
            continue
        if f_member is not None and w["member_id"] != f_member:
            continue
        if f_pack is not None and w["credit_pack_id"] != f_pack:
            continue
        if f_promoted is not None and w["promoted_reservation_id"] != f_promoted:
            continue
        if role == ROLE_MEMBER and w["member_id"] != user_id:
            continue
        records.append(w)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([waitlist_out(w) for w in page], limit, offset, total)


@bp.route("/studios/<studio_id>/sessions/<session_id>/waitlist/<entry_id>/leave", methods=["POST"])
def leave_waitlist(studio_id, session_id, entry_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_MEMBER})
    rec = lookup.get_waitlist_in_session(studio_id, session_id, entry_id)
    session = db.sessions[session_id]

    if user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only leave their own waitlist entries")
    if rec["status"] != "WAITING":
        raise err(ERR_INVALID_STATE, "Waitlist entry is not WAITING")

    rec["status"] = "CANCELLED"
    touch(rec)
    touch(session)  # waitlist_count recompute
    return success_object(waitlist_out(rec), 200)
