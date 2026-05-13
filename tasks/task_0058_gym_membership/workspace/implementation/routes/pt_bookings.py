"""PT bookings and packages."""
from flask import Blueprint, request, g
from db import state, new_id
from errors import raise_err
from response import success_object
from middleware import require_roles, is_role
from routes.helpers import get_json, require_member_ownership
from serializers import serialize_pt_booking, serialize_pt_package
from services import pt as pt_svc, package as pkg_svc


bp = Blueprint("pt", __name__)


@bp.route("/pt-bookings", methods=["POST"])
def create_pt_booking():
    require_roles("Member", "StaffOps", "PlatformAdmin")
    body = get_json()
    member_id = body.get("member_id")
    slot_id = body.get("slot_id")
    billing_mode = body.get("billing_mode")
    package_id = body.get("package_id")
    if not member_id or not slot_id or not billing_mode:
        raise_err("ERR_VALIDATION", "member_id, slot_id, billing_mode required")
    require_member_ownership(member_id)
    b = pt_svc.book_pt(member_id, slot_id, billing_mode, package_id)
    return success_object(serialize_pt_booking(b), status=201)


def _booking_ownership(booking):
    if is_role("Member") and booking["member_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "not member's booking")
    if is_role("Trainer") and booking["trainer_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "not trainer's booking")


@bp.route("/pt-bookings/<id_>/cancel", methods=["POST"])
def cancel_pt(id_):
    require_roles("Member", "StaffOps", "PlatformAdmin")
    b = state["pt_bookings"].get(id_)
    if not b:
        raise_err("ERR_NOT_FOUND", "booking not found")
    if is_role("Member") and b["member_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "not member's booking")
    pt_svc.cancel_pt(b)
    return success_object(serialize_pt_booking(b))


@bp.route("/pt-bookings/<id_>/complete", methods=["POST"])
def complete_pt(id_):
    require_roles("Trainer", "StaffOps", "PlatformAdmin")
    b = state["pt_bookings"].get(id_)
    if not b:
        raise_err("ERR_NOT_FOUND", "booking not found")
    if is_role("Trainer") and b["trainer_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN", "not trainer's booking")
    pt_svc.complete_pt(b)
    return success_object(serialize_pt_booking(b))


@bp.route("/pt-bookings/<id_>/no-show", methods=["POST"])
def no_show_pt(id_):
    require_roles("StaffOps", "PlatformAdmin")
    b = state["pt_bookings"].get(id_)
    if not b:
        raise_err("ERR_NOT_FOUND", "booking not found")
    pt_svc.no_show_pt(b)
    return success_object(serialize_pt_booking(b))


@bp.route("/pt-packages", methods=["POST"])
def create_package():
    require_roles("Member", "StaffOps", "PlatformAdmin")
    body = get_json()
    member_id = body.get("member_id")
    trainer_id = body.get("trainer_id")
    total_sessions = body.get("total_sessions")
    gross_price_cents = body.get("gross_price_cents")
    if not member_id or not trainer_id:
        raise_err("ERR_VALIDATION", "member_id and trainer_id required")
    if not isinstance(total_sessions, int):
        raise_err("ERR_VALIDATION", "total_sessions must be integer")
    if not isinstance(gross_price_cents, int):
        raise_err("ERR_VALIDATION", "gross_price_cents must be integer")
    require_member_ownership(member_id)
    pkg = pkg_svc.sell_package(member_id, trainer_id, total_sessions, gross_price_cents,
                                g.user_role, g.user_id)
    return success_object(serialize_pt_package(pkg), status=201)


@bp.route("/pt-packages/<id_>/refund", methods=["POST"])
def refund_package_route(id_):
    require_roles("StaffOps", "PlatformAdmin")
    pkg = state["pt_packages"].get(id_)
    if not pkg:
        raise_err("ERR_NOT_FOUND", "package not found")
    pkg_svc.refund_package(pkg, g.user_role, g.user_id)
    return success_object(serialize_pt_package(pkg))
