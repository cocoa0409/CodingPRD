"""ClassSeries + Enrollment routes (PRD §3.10, §3.11; SCAFFOLD §1.5).

RBAC:
  POST /class-series                      StudioManager
  GET  /class-series/{id}                 StudioStaff, StudioManager, LoyaltyMember
  GET  /class-series                      StudioStaff, StudioManager, LoyaltyMember
  POST /class-series/{id}/enroll          StudioStaff, StudioManager, LoyaltyMember(own member_id)
  POST /class-series/{id}/start           StudioManager
  POST /class-series/{id}/cancel          StudioManager
  GET  /class-series/{id}/enrollments     StudioStaff, StudioManager
  GET  /enrollments/{id}                  StudioStaff, StudioManager, LoyaltyMember(own)
  POST /enrollments/{id}/mark-attended    StudioStaff, StudioManager
  POST /enrollments/{id}/withdraw         StudioStaff, StudioManager, LoyaltyMember(own)
"""

from flask import Blueprint, request

from clock import clock, parse_iso
from db import db, new_id, stamp_common, touch
from errors import (ApiError, invalid_state, not_resource_owner,
                    ERR_SERIES_FULL, ERR_DUPLICATE_ENROLLMENT,
                    ERR_ENROLLMENT_CLOSED, ERR_MEMBER_SUSPENDED)
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers, calculations, loyalty
from services.lookup import get_series, get_enrollment, get_member, assert_member_owns
from services.validation import require_body, require_str, require_int

bp = Blueprint("class_series", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
STAFF_MANAGER_MEMBER = {"StudioStaff", "StudioManager", "LoyaltyMember"}


def _recompute_enrolled_count(series):
    """enrolled_count = count of Enrollment rows in {ENROLLED, ATTENDED}."""
    count = 0
    for e in db.enrollments.values():
        if e["class_series_id"] == series["id"] and e["status"] in ("ENROLLED", "ATTENDED"):
            count += 1
    series["enrolled_count"] = count
    return count


@bp.route("/class-series", methods=["POST"])
def create_series():
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    payload = require_body(request.get_json(silent=True))
    title = require_str(payload, "title")
    session_count = require_int(payload, "session_count", minimum=1)
    seat_capacity = require_int(payload, "seat_capacity", minimum=1)
    price_cents = require_int(payload, "price_cents", minimum=1)
    starts_at = require_str(payload, "starts_at")
    # validate ISO format
    from errors import invalid_request
    try:
        parse_iso(starts_at)
    except ValueError:
        raise invalid_request("starts_at must be an ISO 8601 instant")

    record = {
        "id": new_id(),
        "title": title,
        "session_count": session_count,
        "seat_capacity": seat_capacity,
        "enrolled_count": 0,
        "price_cents": price_cents,
        "starts_at": starts_at,
        "status": "OPEN",
    }
    stamp_common(record)
    db.class_series[record["id"]] = record
    return success(serializers.class_series(record), status=201)


@bp.route("/class-series/<series_id>", methods=["GET"])
def fetch_series(series_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    series = get_series(series_id)
    return success(serializers.class_series(series))


@bp.route("/class-series", methods=["GET"])
def list_series():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    limit, offset = parse_pagination(request.args)
    records = list(db.class_series.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.class_series(r) for r in window], limit, offset, total)


@bp.route("/class-series/<series_id>/enroll", methods=["POST"])
def enroll(series_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    # Existence: series, then member (left-to-right; PRD §2.8).
    series = get_series(series_id)
    payload = require_body(request.get_json(silent=True))
    member_id = require_str(payload, "member_id")
    member = get_member(member_id)

    # Ownership: a LoyaltyMember must enroll with their own member_id (PRD §3.10).
    if caller.is_member and member_id != caller.user_id:
        raise not_resource_owner("Member may only enroll themselves")

    # State: series must be OPEN (PRD §3.10). A FULL/STARTED/CANCELLED series is
    # surfaced via the more specific business errors / invalid state.
    if series["status"] != "OPEN":
        # If full, surface ERR_SERIES_FULL; otherwise invalid state.
        if series["status"] == "FULL":
            raise ApiError(ERR_SERIES_FULL, 409, "Series is full")
        raise invalid_state("Series is not OPEN")

    # Business: full (defensive — enrolled_count reached seat_capacity).
    if series["enrolled_count"] >= series["seat_capacity"]:
        raise ApiError(ERR_SERIES_FULL, 409, "Series is full")

    # Business: duplicate non-cancelled enrollment (PRD §3.10).
    for e in db.enrollments.values():
        if (e["class_series_id"] == series_id and e["member_id"] == member_id
                and e["status"] in ("ENROLLED", "ATTENDED")):
            raise ApiError(ERR_DUPLICATE_ENROLLMENT, 409,
                           "Member already enrolled in this series")

    # Business temporal: enrollment window closed (PRD §3.10).
    if clock.now() >= parse_iso(series["starts_at"]):
        raise ApiError(ERR_ENROLLMENT_CLOSED, 409, "Enrollment window closed")

    # Business: suspended member may not enroll (PRD §3.10).
    if member["status"] == "SUSPENDED":
        raise ApiError(ERR_MEMBER_SUSPENDED, 409, "Suspended member may not enroll")

    # Snapshot price; compute and credit class loyalty (PRD §3.10).
    amount_paid = series["price_cents"]
    points_earned = calculations.enrollment_points_earned(
        amount_paid, series["session_count"])

    enrollment = {
        "id": new_id(),
        "class_series_id": series_id,
        "member_id": member_id,
        "amount_paid_cents": amount_paid,
        "points_earned": points_earned,
        "status": "ENROLLED",
    }
    stamp_common(enrollment)
    db.enrollments[enrollment["id"]] = enrollment

    # Credit member, append EARN ledger, recompute tier (PRD §3.10).
    if points_earned > 0:
        loyalty.credit_earn(member, points_earned, "ENROLLMENT", enrollment["id"])
        touch(member)

    # enrolled_count += 1; bubble OPEN -> FULL if now full.
    _recompute_enrolled_count(series)
    if series["status"] == "OPEN" and series["enrolled_count"] >= series["seat_capacity"]:
        series["status"] = "FULL"
    touch(series)

    return success(serializers.enrollment(enrollment), status=201)


@bp.route("/class-series/<series_id>/start", methods=["POST"])
def start_series_endpoint(series_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    series = get_series(series_id)

    # State: OPEN or FULL (PRD §3.11).
    if series["status"] not in ("OPEN", "FULL"):
        raise invalid_state("Series is not OPEN or FULL")
    # Clock must have reached starts_at (PRD §3.11).
    if not (clock.now() >= parse_iso(series["starts_at"])):
        raise invalid_state("Series start time has not been reached")

    series["status"] = "STARTED"
    touch(series)
    return success(serializers.class_series(series))


@bp.route("/class-series/<series_id>/cancel", methods=["POST"])
def cancel_series(series_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    series = get_series(series_id)

    # State: OPEN or FULL (PRD §3.11).
    if series["status"] not in ("OPEN", "FULL"):
        raise invalid_state("Series is not OPEN or FULL")

    # Cascade: every still-ENROLLED enrollment -> REFUNDED with point reversal.
    for e in db.enrollments.values():
        if e["class_series_id"] == series_id and e["status"] == "ENROLLED":
            member = db.loyalty_members.get(e["member_id"])
            if member is not None and e["points_earned"] > 0:
                loyalty.reverse_earn(member, e["points_earned"], "ENROLLMENT", e["id"])
                touch(member)
            e["status"] = "REFUNDED"
            touch(e)

    _recompute_enrolled_count(series)
    series["status"] = "CANCELLED"
    touch(series)
    return success(serializers.class_series(series))


@bp.route("/class-series/<series_id>/enrollments", methods=["GET"])
def list_series_enrollments(series_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    series = get_series(series_id)
    limit, offset = parse_pagination(request.args)
    records = [e for e in db.enrollments.values() if e["class_series_id"] == series_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.enrollment(r) for r in window], limit, offset, total)


# ---- Enrollment endpoints ----------------------------------------------------

@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def fetch_enrollment(enrollment_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    enrollment = get_enrollment(enrollment_id)
    assert_member_owns(caller, enrollment["member_id"])
    return success(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/mark-attended", methods=["POST"])
def mark_attended(enrollment_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    enrollment = get_enrollment(enrollment_id)

    # State: ENROLLED (PRD §3.10).
    if enrollment["status"] != "ENROLLED":
        raise invalid_state("Enrollment is not ENROLLED")
    # Parent series must be STARTED (PRD §3.10).
    series = db.class_series.get(enrollment["class_series_id"])
    if series is None or series["status"] != "STARTED":
        raise invalid_state("Parent series is not STARTED")

    enrollment["status"] = "ATTENDED"
    touch(enrollment)
    return success(serializers.enrollment(enrollment))


@bp.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw(enrollment_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    enrollment = get_enrollment(enrollment_id)
    assert_member_owns(caller, enrollment["member_id"])

    # State: ENROLLED (PRD §3.11).
    if enrollment["status"] != "ENROLLED":
        raise invalid_state("Enrollment is not ENROLLED")
    # Parent series must be OPEN or FULL (cannot withdraw after start) (PRD §3.11).
    series = db.class_series.get(enrollment["class_series_id"])
    if series is None or series["status"] not in ("OPEN", "FULL"):
        raise invalid_state("Cannot withdraw after series has started")

    # Reverse the earned loyalty (PRD §3.11).
    member = db.loyalty_members.get(enrollment["member_id"])
    if member is not None and enrollment["points_earned"] > 0:
        loyalty.reverse_earn(member, enrollment["points_earned"], "ENROLLMENT", enrollment["id"])
        touch(member)

    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)

    # enrolled_count -= 1; bubble FULL -> OPEN if a seat reopened.
    _recompute_enrolled_count(series)
    if series["status"] == "FULL" and series["enrolled_count"] < series["seat_capacity"]:
        series["status"] = "OPEN"
    touch(series)

    return success(serializers.enrollment(enrollment))
