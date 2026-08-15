"""OfficerRole and MeetingMinutes endpoints."""

from flask import Blueprint

import db
from core import (as_str, body, caller_active_role, check_frozen, get_chapter,
                  get_minutes, get_role, new_record, recompute_member,
                  require_fields, touch)
from db import now_iso, parse_dt
from errors import (ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_AN_OFFICER,
                    ERR_NOT_FOUND, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("roles_minutes", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")


# --- OfficerRole ---

@bp.route("/chapters/<chapterId>/officer-roles", methods=["GET"])
def list_roles(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [r for r in db.officer_roles.values() if r["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status", "office"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/officer-roles/<roleId>", methods=["GET"])
def fetch_role(chapterId, roleId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    r = get_role(ch, roleId)
    return success(serialize(r), 200)


@bp.route("/chapters/<chapterId>/officer-roles/<roleId>/resign", methods=["POST"])
def resign_role(chapterId, roleId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    r = get_role(ch, roleId)
    check_frozen(ch)
    if r["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE OfficerRole can be resigned")
    if uid != r["member_id"]:
        raise ApiError(ERR_NOT_AN_OFFICER, 403,
                       "Caller does not hold this OfficerRole")
    r["status"] = "RESIGNED"
    r["ended_at"] = now_iso()
    touch(r)
    m = db.members.get(r["member_id"])
    if m is not None:
        recompute_member(m)
    return success(serialize(r), 200)


@bp.route("/chapters/<chapterId>/officer-roles/<roleId>/remove", methods=["POST"])
def remove_role(chapterId, roleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    r = get_role(ch, roleId)
    check_frozen(ch)
    if r["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE OfficerRole can be removed")
    holder = db.members.get(r["member_id"])
    if holder is not None and holder["status"] == "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "An officer may only be removed when the member is no longer ACTIVE")
    r["status"] = "REMOVED"
    r["ended_at"] = now_iso()
    touch(r)
    if holder is not None:
        recompute_member(holder)
    return success(serialize(r), 200)


# --- MeetingMinutes ---

@bp.route("/chapters/<chapterId>/meeting-minutes", methods=["POST"])
def create_minutes(chapterId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    caller_active_role(ch["id"], uid)
    data = body()
    require_fields(data, ["meeting_date", "called_by_officer_id",
                          "attendees_member_ids", "agenda", "notes"])
    called_by = as_str(data["called_by_officer_id"], "called_by_officer_id")
    caller_role = db.officer_roles.get(called_by)
    if caller_role is None or caller_role["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"OfficerRole not found: {called_by}")
    attendees = data["attendees_member_ids"]
    if not isinstance(attendees, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "attendees_member_ids must be an array")
    rec = new_record({
        "chapter_id": ch["id"],
        "meeting_date": db.iso(parse_dt(data["meeting_date"], "meeting_date")),
        "called_by_officer_id": called_by,
        "attendees_member_ids": [as_str(a, "attendees_member_ids[]") for a in attendees],
        "agenda": as_str(data["agenda"], "agenda"),
        "notes": as_str(data["notes"], "notes"),
        "status": "DRAFT",
        "submitted_by_officer_id": None,
        "approved_by_user_id": None,
    })
    db.meeting_minutes[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/meeting-minutes/<minutesId>", methods=["GET"])
def fetch_minutes(chapterId, minutesId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_minutes(ch, minutesId)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/meeting-minutes", methods=["GET"])
def list_minutes(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [m for m in db.meeting_minutes.values() if m["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/meeting-minutes/<minutesId>/submit", methods=["POST"])
def submit_minutes(chapterId, minutesId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    m = get_minutes(ch, minutesId)
    check_frozen(ch)
    if m["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only DRAFT minutes can be submitted")
    secretary = caller_active_role(ch["id"], uid, office="SECRETARY")
    called_by = db.officer_roles.get(m["called_by_officer_id"])
    if called_by is None or called_by["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The officer recorded in called_by_officer_id no longer holds an ACTIVE role")
    m["status"] = "SUBMITTED"
    m["submitted_by_officer_id"] = secretary["id"]
    touch(m)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/meeting-minutes/<minutesId>/approve", methods=["POST"])
def approve_minutes(chapterId, minutesId):
    uid, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_minutes(ch, minutesId)
    check_frozen(ch)
    if m["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only SUBMITTED minutes can be approved")
    m["status"] = "APPROVED"
    m["approved_by_user_id"] = uid
    touch(m)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/meeting-minutes/<minutesId>/amend", methods=["POST"])
def amend_minutes(chapterId, minutesId):
    uid, role = auth()
    require_roles(role, ("Officer",))
    ch = get_chapter(chapterId)
    m = get_minutes(ch, minutesId)
    check_frozen(ch)
    if m["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only APPROVED minutes can be amended")
    caller_active_role(ch["id"], uid, office="SECRETARY")
    data = body()
    require_fields(data, ["notes"])
    notes = as_str(data["notes"], "notes")
    if notes == m["notes"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Amended notes must differ from the prior body")
    m["notes"] = notes
    # APPROVED -> AMENDED -> SUBMITTED; the system returns it to SUBMITTED
    # immediately once the amended body is saved.
    m["status"] = "SUBMITTED"
    touch(m)
    return success(serialize(m), 200)
