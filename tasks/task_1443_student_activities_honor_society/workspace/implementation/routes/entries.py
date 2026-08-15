"""ServiceHourEntry endpoints."""

from decimal import Decimal

from flask import Blueprint

import db
from core import (as_str, body, check_frozen, get_chapter, get_entry, get_member,
                  new_record, recompute_member, require_fields, touch)
from db import now, parse_dt
from errors import (ERR_FUTURE_SERVICE_DATE, ERR_INVALID_REQUEST,
                    ERR_INVALID_SERVICE_HOURS, ERR_INVALID_STATE, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("entries", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")


def _validate_hours(value):
    """hours must be in (0, 12] and an exact multiple of 0.25."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_SERVICE_HOURS, 422,
                       "hours must be a number in (0, 12] in 0.25 increments")
    h = Decimal(str(value))
    if h <= 0 or h > 12 or (h * 4) != (h * 4).to_integral_value():
        raise ApiError(ERR_INVALID_SERVICE_HOURS, 422,
                       "hours must be in (0, 12] and an exact multiple of 0.25")
    return float(h)


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries", methods=["POST"])
def create_entry(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Member", "Officer", "Advisor"))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["activity_name", "service_date", "hours",
                          "organization", "supervisor_email"])
    hours = _validate_hours(data["hours"])
    service_date = parse_dt(data["service_date"], "service_date")
    if service_date > now():
        raise ApiError(ERR_FUTURE_SERVICE_DATE, 422,
                       "service_date must not lie in the future")
    rec = new_record({
        "chapter_id": ch["id"],
        "member_id": m["id"],
        "activity_name": as_str(data["activity_name"], "activity_name"),
        "service_date": db.iso(service_date),
        "hours": hours,
        "organization": as_str(data["organization"], "organization"),
        "supervisor_email": as_str(data["supervisor_email"], "supervisor_email"),
        "status": "PENDING_VERIFICATION",
        "verified_by_user_id": None,
        "rejection_reason": None,
    })
    db.service_entries[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries", methods=["GET"])
def list_entries(chapterId, memberId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    items = [e for e in db.service_entries.values() if e["member_id"] == m["id"]]
    items = apply_filters(items, ["status"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries/<entryId>", methods=["GET"])
def fetch_entry(chapterId, memberId, entryId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    e = get_entry(m, entryId)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries/<entryId>/verify", methods=["POST"])
def verify_entry(chapterId, memberId, entryId):
    uid, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    e = get_entry(m, entryId)
    check_frozen(ch)
    # state-first ordering: invalid states before the hours rule, hours before the date rule
    if e["status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING_VERIFICATION entry can be verified")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chapter must be ACTIVE to verify entries")
    if m["status"] not in ("ACTIVE", "ON_PROBATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member must be ACTIVE or ON_PROBATION to verify entries")
    _validate_hours(e["hours"])
    if parse_dt(e["service_date"], "service_date") > now():
        raise ApiError(ERR_FUTURE_SERVICE_DATE, 422,
                       "service_date must not lie in the future")
    e["status"] = "VERIFIED"
    e["verified_by_user_id"] = uid
    touch(e)
    recompute_member(m)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries/<entryId>/reject", methods=["POST"])
def reject_entry(chapterId, memberId, entryId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    e = get_entry(m, entryId)
    check_frozen(ch)
    if e["status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PENDING_VERIFICATION entry can be rejected")
    data = body()
    if not data.get("rejection_reason") or not isinstance(data.get("rejection_reason"), str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "rejection_reason is required")
    e["status"] = "REJECTED"
    e["rejection_reason"] = data["rejection_reason"]
    touch(e)
    recompute_member(m)
    return success(serialize(e), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/service-hour-entries/<entryId>/void", methods=["POST"])
def void_entry(chapterId, memberId, entryId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    e = get_entry(m, entryId)
    check_frozen(ch)
    was_verified = e["status"] == "VERIFIED"
    if e["status"] == "PENDING_VERIFICATION":
        pass
    elif was_verified:
        if ch["standing"] == "REVOKED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Cannot void a VERIFIED entry while chapter standing is REVOKED")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING_VERIFICATION or VERIFIED entry can be voided")
    e["status"] = "VOID"
    touch(e)
    if was_verified:
        recompute_member(m)
    return success(serialize(e), 200)
