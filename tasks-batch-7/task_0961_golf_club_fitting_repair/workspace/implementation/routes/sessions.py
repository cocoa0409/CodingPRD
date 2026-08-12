"""Fitting session endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination, parse_iso
from services.common import (
    new_entity, touch, get_session, get_customer, get_bay, get_staff,
    get_package, check_create_ownership, check_ownership,
)
from services.serializers import serialize_fitting_session

bp = Blueprint("sessions", __name__)

READ_ROLES = {"ShopAdmin", "ShopManager", "FittingSpecialist",
              "RepairTechnician", "Instructor", "Customer"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/fitting-sessions")
def create_session():
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist", "Customer"})
    data = _body()
    customer_id = data.get("customer_id")
    bay_id = data.get("bay_id")
    specialist_id = data.get("specialist_id")
    lesson_package_id = data.get("lesson_package_id")
    starts_raw = data.get("starts_at")
    ends_raw = data.get("ends_at")

    # Body shape validation (priority 3)
    for field, val in (("customer_id", customer_id), ("bay_id", bay_id),
                       ("specialist_id", specialist_id)):
        if not isinstance(val, str) or not val.strip():
            raise_err("ERR_VALIDATION", f"{field} is required")
    if lesson_package_id is not None and (
            not isinstance(lesson_package_id, str) or not lesson_package_id.strip()):
        raise_err("ERR_VALIDATION", "lesson_package_id must be a string id")
    try:
        starts_at = parse_iso(starts_raw)
        ends_at = parse_iso(ends_raw)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", "starts_at and ends_at must be ISO8601 timestamps")
    if not (starts_at < ends_at):
        raise_err("ERR_VALIDATION", "starts_at must be strictly earlier than ends_at")

    # Existence of body FK ids (priority 4)
    customer = get_customer(customer_id)
    bay = get_bay(bay_id)
    get_staff(specialist_id)
    package = None
    if lesson_package_id is not None:
        package = get_package(lesson_package_id)

    # Ownership (priority 5): Customer caller can only book for themselves
    check_create_ownership(customer_id, user_id, role)

    # Temporal rules (priority 9): bay conflict before specialist conflict
    relevant = [
        s for s in db.fitting_sessions.values()
        if s["status"] in ("BOOKED", "CHECKED_IN")
    ]
    buffer = timedelta(minutes=bay["cleanup_buffer_minutes"])
    for existing in relevant:
        if existing["bay_id"] != bay_id:
            continue
        # Buffered half-open: no conflict iff new.ends <= exist.starts - buffer
        # OR new.starts >= exist.ends + buffer. Exactly buffer gap is allowed.
        if ends_at <= existing["starts_at"] - buffer:
            continue
        if starts_at >= existing["ends_at"] + buffer:
            continue
        raise_err("ERR_BAY_TIME_CONFLICT", "session violates the bay overlap rule")
    for existing in relevant:
        if existing["specialist_id"] != specialist_id:
            continue
        # Closed interval, no buffer: adjacency (end == start) IS a conflict.
        if starts_at <= existing["ends_at"] and ends_at >= existing["starts_at"]:
            raise_err("ERR_SPECIALIST_TIME_CONFLICT",
                      "session violates the specialist overlap rule")

    # Fiscal rules (priority 10): lesson package credit consumption
    credit_consumed = False
    if package is not None:
        if package["status"] == "EXPIRED":
            raise_err("ERR_PACKAGE_NOT_ACTIVE",
                      "lesson package is not active")
        if package["credits_used"] >= package["total_credits"]:
            raise_err("ERR_NO_CREDITS_REMAINING",
                      "lesson package has no credits remaining")
        package["credits_used"] += 1
        if package["credits_used"] == package["total_credits"] and package["status"] == "ACTIVE":
            package["status"] = "EXHAUSTED"
        touch(package)
        credit_consumed = True

    s = new_entity()
    s.update({
        "customer_id": customer_id,
        "bay_id": bay_id,
        "specialist_id": specialist_id,
        "lesson_package_id": lesson_package_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "BOOKED",
        "credit_consumed": credit_consumed,
        "credit_refunded": False,
    })
    db.fitting_sessions[s["id"]] = s
    return success_response(serialize_fitting_session(s), status=201)


@bp.get("/fitting-sessions/<sid>")
def read_session(sid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    s = get_session(sid)
    check_ownership(s, user_id, role)
    return success_response(serialize_fitting_session(s))


@bp.get("/fitting-sessions")
def list_sessions():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.fitting_sessions.values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == user_id]
    for field in ("customer_id", "bay_id", "specialist_id", "lesson_package_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    items.sort(key=lambda s: s["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_fitting_session(s) for s in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/fitting-sessions/<sid>/check-in")
def check_in_session(sid):
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist"})
    s = get_session(sid)
    if s["status"] != "BOOKED":
        raise_err("ERR_SESSION_NOT_BOOKED", "session is not in BOOKED")
    bay = db.bays.get(s["bay_id"])
    if bay is None or bay["status"] != "AVAILABLE":
        raise_err("ERR_BAY_UNAVAILABLE", "bay is in MAINTENANCE")
    s["status"] = "CHECKED_IN"
    touch(s)
    return success_response(serialize_fitting_session(s))


@bp.post("/fitting-sessions/<sid>/complete")
def complete_session(sid):
    user_id, role = get_auth()
    require_role(role, {"FittingSpecialist"})
    s = get_session(sid)
    if s["status"] != "CHECKED_IN":
        raise_err("ERR_SESSION_NOT_CHECKED_IN", "session is not in CHECKED_IN")
    s["status"] = "COMPLETED"
    touch(s)
    return success_response(serialize_fitting_session(s))


@bp.post("/fitting-sessions/<sid>/cancel")
def cancel_session(sid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "FittingSpecialist", "ShopManager"})
    s = get_session(sid)
    check_ownership(s, user_id, role)
    if s["status"] != "BOOKED":
        raise_err("ERR_SESSION_NOT_BOOKED", "session is not in BOOKED")
    # Lesson credit refund: cancellation >= 24h before starts_at refunds
    # (threshold inclusive: exactly 24h refunds).
    if s["credit_consumed"] and not s["credit_refunded"]:
        if s["starts_at"] - db.logical_now >= timedelta(hours=24):
            package = db.lesson_packages.get(s["lesson_package_id"])
            if package is not None:
                package["credits_used"] -= 1
                if package["status"] == "EXHAUSTED" and package["credits_used"] < package["total_credits"]:
                    package["status"] = "ACTIVE"
                touch(package)
            s["credit_refunded"] = True
    s["status"] = "CANCELLED"
    touch(s)
    return success_response(serialize_fitting_session(s))
