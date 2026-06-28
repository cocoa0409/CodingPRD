"""Appointment routes: book, list, get, complete, cancel, no-show (PRD §3.5-3.8)."""
from flask import Blueprint, request

import errors
from clock import parse_iso8601
from common import bad_request, get_json_body, parse_pagination, paginate, sort_by_created
from db import store
from lookups import (get_appointment_or_404, get_member_or_404,
                     get_service_type_or_404, ownership_member, ownership_tech)
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import appointment_lifecycle, booking
import serialize

bp = Blueprint("appointments", __name__)

READ_ROLES = {"StudioManager", "FrontDesk", "LashTech", "Member"}


@bp.route("/appointments", methods=["POST"])
def book_appointment():
    user_id, role = get_user_context()
    # Priority 2 — role permitted.
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    body = get_json_body()

    # member_id / service_type_id are required references; their presence is a
    # field-shape concern, but the PRD orders body FK existence (priority 4)
    # ahead of field-shape (priority 14). When present we resolve existence;
    # when absent we surface the field-shape error.
    member_id = body.get("member_id")
    service_type_id = body.get("service_type_id")
    if not isinstance(member_id, str) or member_id == "":
        raise bad_request("member_id is required.")
    if not isinstance(service_type_id, str) or service_type_id == "":
        raise bad_request("service_type_id is required.")

    # Priority 4 — body FK existence (member, service_type, membership).
    member = get_member_or_404(member_id)
    service_type = get_service_type_or_404(service_type_id)
    # Both must belong to the same studio (PRD §2.8). studio taken from member.
    if service_type["studio_id"] != member["studio_id"]:
        raise errors.ApiError(errors.ERR_SERVICE_TYPE_NOT_FOUND, 404,
                              "Service type not in member's studio.")

    pay_with_credits = body.get("pay_with_credits", False)
    if not isinstance(pay_with_credits, bool):
        raise bad_request("pay_with_credits must be a boolean.")

    membership = None
    expected_version = None
    if pay_with_credits:
        membership_id = body.get("membership_id")
        if not isinstance(membership_id, str) or membership_id == "":
            raise bad_request("membership_id is required when paying with credits.")
        membership = store.memberships.get(membership_id)
        if not membership:
            raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_FOUND, 404, "Membership not found.")
        if membership["member_id"] != member["id"]:
            raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_FOUND, 404,
                                  "Membership does not belong to the member.")
        expected_version = body.get("expected_membership_version")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise bad_request("expected_membership_version is required and must be an integer.")

    # Member may only book for themselves (PRD §2.1, §3.5).
    ownership_member(role, user_id, member["id"])

    # Field-shape: start_utc parseable (priority 14, after the above resolution).
    start_raw = body.get("start_utc")
    if start_raw is None:
        raise bad_request("start_utc is required.")
    try:
        start_utc = parse_iso8601(start_raw)
    except (ValueError, TypeError):
        raise bad_request("start_utc is not a valid ISO 8601 timestamp.")

    appt = booking.run_booking(
        member=member,
        service_type=service_type,
        start_utc=start_utc,
        pay_with_credits=pay_with_credits,
        membership=membership,
        expected_membership_version=expected_version,
        recurring_schedule_id=None,
        schedule_context=False,
    )
    return success_object(serialize.appointment_out(appt), status=201)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.appointments.values())
    for key in ("studio_id", "member_id", "lash_tech_id", "service_type_id",
                "membership_id", "recurring_schedule_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    # Ownership scoping for entity-backed roles.
    if role == "Member":
        items = [a for a in items if a["member_id"] == user_id]
    elif role == "LashTech":
        items = [a for a in items if a["lash_tech_id"] == user_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.appointment_out(a) for a in page], limit, offset, total)


@bp.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    a = get_appointment_or_404(aid)
    if role == "Member":
        ownership_member(role, user_id, a["member_id"])
    elif role == "LashTech":
        ownership_tech(role, user_id, a["lash_tech_id"])
    return success_object(serialize.appointment_out(a))


@bp.route("/appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    user_id, role = get_user_context()
    require_role(role, {"LashTech", "StudioManager"})
    a = get_appointment_or_404(aid)
    # Completion performed by the assigned LashTech (or a StudioManager).
    if role == "LashTech":
        ownership_tech(role, user_id, a["lash_tech_id"])
    appointment_lifecycle.complete(a)
    return success_object(serialize.appointment_out(a))


@bp.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    user_id, role = get_user_context()
    require_role(role, {"Member", "FrontDesk", "StudioManager"})
    a = get_appointment_or_404(aid)
    if role == "Member":
        ownership_member(role, user_id, a["member_id"])
    appointment_lifecycle.cancel(a)
    return success_object(serialize.appointment_out(a))


@bp.route("/appointments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    _, role = get_user_context()
    require_role(role, {"FrontDesk", "StudioManager"})
    a = get_appointment_or_404(aid)
    appointment_lifecycle.mark_no_show(a)
    return success_object(serialize.appointment_out(a))


@bp.route("/appointments/<aid>/retail-orders", methods=["GET"])
def list_appointment_retail_orders(aid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    a = get_appointment_or_404(aid)
    if role == "Member":
        ownership_member(role, user_id, a["member_id"])
    limit, offset = parse_pagination()
    items = [o for o in store.retail_orders.values() if o["appointment_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.retail_order_out(o) for o in page], limit, offset, total)
