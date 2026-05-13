"""Group class and booking endpoints."""
from flask import Blueprint, request, g
from clock import from_iso
from db import state, new_id
from errors import raise_err
from response import success_object
from middleware import require_roles, is_role
from routes.helpers import get_json, require_member_ownership, check_occ
from serializers import serialize_group_class, serialize_group_booking
from services import group as group_svc


bp = Blueprint("groups", __name__)


@bp.route("/group-classes", methods=["POST"])
def create_class():
    require_roles("PlatformAdmin", "StaffOps")
    body = get_json()
    class_code = body.get("class_code")
    instructor_trainer_id = body.get("instructor_trainer_id")
    starts_at = body.get("starts_at")
    ends_at = body.get("ends_at")
    capacity = body.get("capacity")
    recurrence_series_id = body.get("recurrence_series_id")
    deduction_cents = body.get("deduction_cents", 0)
    if not class_code or not instructor_trainer_id or not starts_at or not ends_at:
        raise_err("ERR_VALIDATION", "missing required fields")
    if not isinstance(capacity, int):
        raise_err("ERR_VALIDATION", "capacity must be integer")
    if not isinstance(deduction_cents, int):
        raise_err("ERR_VALIDATION", "deduction_cents must be integer")
    try:
        starts_at_dt = from_iso(starts_at)
        ends_at_dt = from_iso(ends_at)
    except ValueError:
        raise_err("ERR_VALIDATION", "invalid timestamp")
    gc = group_svc.create_class(
        class_code, instructor_trainer_id, starts_at_dt, ends_at_dt,
        capacity, recurrence_series_id, deduction_cents,
    )
    return success_object(serialize_group_class(gc), status=201)


@bp.route("/group-classes/<id_>", methods=["PATCH"])
def patch_class(id_):
    require_roles("PlatformAdmin", "StaffOps")
    gc = state["group_classes"].get(id_)
    if not gc:
        raise_err("ERR_NOT_FOUND", "class not found")
    body = get_json()
    check_occ(gc, body)
    group_svc.patch_class(gc, body)
    return success_object(serialize_group_class(gc))


@bp.route("/group-classes/<id_>/cancel", methods=["POST"])
def cancel_class_route(id_):
    require_roles("PlatformAdmin", "StaffOps")
    gc = state["group_classes"].get(id_)
    if not gc:
        raise_err("ERR_NOT_FOUND", "class not found")
    group_svc.cancel_class(gc)
    return success_object(serialize_group_class(gc))


@bp.route("/group-bookings", methods=["POST"])
def create_group_booking():
    require_roles("Member", "StaffOps", "PlatformAdmin")
    body = get_json()
    class_id = body.get("class_id")
    member_id = body.get("member_id")
    card_id = body.get("card_id")
    accept_waitlist = body.get("accept_waitlist")
    if not class_id or not member_id:
        raise_err("ERR_VALIDATION", "class_id and member_id required")
    require_member_ownership(member_id)
    b = group_svc.book_group(member_id, class_id, card_id, accept_waitlist)
    return success_object(serialize_group_booking(b), status=201)


@bp.route("/group-bookings/<id_>/cancel", methods=["POST"])
def cancel_group_booking_route(id_):
    require_roles("Member", "StaffOps", "PlatformAdmin")
    b = state["group_bookings"].get(id_)
    if not b:
        raise_err("ERR_NOT_FOUND", "booking not found")
    if is_role("Member") and b["member_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "not member's booking")
    group_svc.cancel_group_booking(b)
    return success_object(serialize_group_booking(b))


@bp.route("/group-bookings/<id_>/check-in", methods=["POST"])
def check_in_route(id_):
    require_roles("StaffOps", "PlatformAdmin")
    b = state["group_bookings"].get(id_)
    if not b:
        raise_err("ERR_NOT_FOUND", "booking not found")
    group_svc.check_in(b)
    return success_object(serialize_group_booking(b))
