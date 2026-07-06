"""VolunteerAssignment endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso8601,
    clock_now_dt, clock_now_iso,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_DEPENDENCY_STATE, ERR_MEMBERSHIP_INELIGIBLE, ERR_VOLUNTEER_OVERLAP,
    ERR_FORBIDDEN,
)
from datetime import timedelta

bp = Blueprint("volunteer_assignments", __name__)

ROLE_TYPES = {"USHER", "GREETER", "CHILDCARE", "AUDIO_VISUAL", "TEACHER"}


@bp.route("/volunteer-assignments", methods=["POST"])
def create_assignment():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("event_id", "member_id", "role_type"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if body["role_type"] not in ROLE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "invalid role_type")

    event = db.events.get(body["event_id"])
    if event is None:
        raise_err(ERR_NOT_FOUND, "event_id not found")
    member = db.members.get(body["member_id"])
    if member is None:
        raise_err(ERR_NOT_FOUND, "member_id not found")

    # Rung 13: CHILDCARE requires ADULT + REGULAR/MEMBER.
    if body["role_type"] == "CHILDCARE":
        if member.get("member_type") != "ADULT":
            raise_err(ERR_MEMBERSHIP_INELIGIBLE, "CHILDCARE volunteer must be ADULT")
        if member.get("membership_status") not in ("REGULAR", "MEMBER"):
            raise_err(ERR_MEMBERSHIP_INELIGIBLE, "CHILDCARE volunteer must be REGULAR or MEMBER")

    rec = {
        "event_id": event["id"],
        "member_id": member["id"],
        "role_type": body["role_type"],
        "status": "INVITED",
        "accepted_at": None,
    }
    stamp_common_create(rec)
    db.volunteer_assignments[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/volunteer-assignments/<vid>", methods=["GET"])
def get_assignment(vid):
    role, user_id = require_role({"Coordinator", "Member", "PlatformAdmin"})
    rec = must_exist(db.volunteer_assignments, vid, "VolunteerAssignment")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only view their own assignments")
    return success(rec, 200)


@bp.route("/volunteer-assignments/<vid>/accept", methods=["POST"])
def accept_assignment(vid):
    role, user_id = require_role({"Member", "PlatformAdmin"})
    rec = must_exist(db.volunteer_assignments, vid, "VolunteerAssignment")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only accept their own assignments")
    if rec["status"] != "INVITED":
        raise_err(ERR_INVALID_STATE, "assignment must be INVITED to accept")
    event = db.events.get(rec["event_id"])
    if event is None or event.get("status") != "SCHEDULED":
        raise_err(ERR_DEPENDENCY_STATE, "event is not SCHEDULED")
    member = db.members.get(rec["member_id"])
    if member is None or member.get("membership_status") == "DEPARTED":
        raise_err(ERR_DEPENDENCY_STATE, "member is DEPARTED")

    # Rung 8: volunteer overlap.
    new_start = parse_iso8601(event["starts_at"])
    new_end = parse_iso8601(event["ends_at"])
    for other in db.volunteer_assignments.values():
        if other["id"] == vid:
            continue
        if other.get("member_id") != rec["member_id"]:
            continue
        if other.get("status") not in ("ACCEPTED", "CHECKED_IN"):
            continue
        o_event = db.events.get(other.get("event_id"))
        if o_event is None:
            continue
        try:
            o_start = parse_iso8601(o_event["starts_at"])
            o_end = parse_iso8601(o_event["ends_at"])
        except Exception:
            continue
        # Half-open unbuffered.
        if new_start < o_end and o_start < new_end:
            raise_err(ERR_VOLUNTEER_OVERLAP, "assignment overlaps another accepted assignment")

    rec["status"] = "ACCEPTED"
    rec["accepted_at"] = clock_now_iso()
    bump(rec)
    event["volunteer_filled_count"] = event.get("volunteer_filled_count", 0) + 1
    bump(event)
    return success(rec, 200)


@bp.route("/volunteer-assignments/<vid>/decline", methods=["POST"])
def decline_assignment(vid):
    role, user_id = require_role({"Member", "PlatformAdmin"})
    rec = must_exist(db.volunteer_assignments, vid, "VolunteerAssignment")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only decline their own assignments")
    if rec["status"] != "INVITED":
        raise_err(ERR_INVALID_STATE, "assignment must be INVITED to decline")
    rec["status"] = "DECLINED"
    bump(rec)
    return success(rec, 200)


@bp.route("/volunteer-assignments/<vid>/cancel", methods=["POST"])
def cancel_assignment(vid):
    role, user_id = require_role({"Coordinator", "Member", "PlatformAdmin"})
    rec = must_exist(db.volunteer_assignments, vid, "VolunteerAssignment")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only cancel their own assignments")
    if rec["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "assignment must be ACCEPTED to cancel")
    rec["status"] = "CANCELLED"
    bump(rec)
    event = db.events.get(rec["event_id"])
    if event is not None:
        event["volunteer_filled_count"] = max(0, event.get("volunteer_filled_count", 0) - 1)
        bump(event)
    return success(rec, 200)


@bp.route("/volunteer-assignments/<vid>/checkin", methods=["POST"])
def checkin_assignment(vid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.volunteer_assignments, vid, "VolunteerAssignment")
    if rec["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "assignment must be ACCEPTED to check in")
    event = db.events.get(rec["event_id"])
    if event is None:
        raise_err(ERR_NOT_FOUND, "event not found")
    starts = parse_iso8601(event["starts_at"])
    ends = parse_iso8601(event["ends_at"])
    now = clock_now_dt()
    if now < starts - timedelta(minutes=60) or now > ends:
        raise_err(ERR_INVALID_STATE, "not within check-in window")
    rec["status"] = "CHECKED_IN"
    bump(rec)
    return success(rec, 200)


@bp.route("/volunteer-assignments", methods=["GET"])
def list_assignments():
    role, user_id = require_role({"Coordinator", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.volunteer_assignments.values())
    if role == "Member":
        items = [v for v in items if v["member_id"] == user_id]
    for k in ("event_id", "member_id", "status"):
        v = request.args.get(k)
        if v:
            items = [x for x in items if x.get(k) == v]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
