"""RetailOrder routes (PRD §3.9)."""
from flask import Blueprint, request

import errors
from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_str, sort_by_created, stamp_create, touch)
from db import store
from lookups import get_member_or_404, ownership_member
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import retail as retail_service
import serialize

bp = Blueprint("retail", __name__)


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) < 1:
        raise bad_request("lines must be a non-empty array.")
    for line in lines:
        if not isinstance(line, dict):
            raise bad_request("each line must be an object.")
        sku = line.get("sku")
        if not isinstance(sku, str) or sku == "":
            raise bad_request("each line requires a non-empty sku.")
        unit = line.get("unit_price_cents")
        if not isinstance(unit, int) or isinstance(unit, bool) or unit <= 0:
            raise bad_request("each line requires a positive unit_price_cents.")
        qty = line.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise bad_request("each line requires a positive quantity.")


@bp.route("/retail-orders", methods=["POST"])
def create_retail_order():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    body = get_json_body()
    member_id = require_str(body, "member_id")
    member = get_member_or_404(member_id)
    ownership_member(role, user_id, member["id"])

    appointment_id = body.get("appointment_id")
    if not isinstance(appointment_id, str) or appointment_id == "":
        raise bad_request("appointment_id is required.")
    appt = store.appointments.get(appointment_id)
    if not appt:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Appointment not found.")

    lines = body.get("lines")
    _validate_lines(lines)

    # Referential business rule (priority 6): appointment must be a BOOKED
    # appointment belonging to the same member (PRD §3.9).
    if appt["member_id"] != member["id"] or appt["status"] != "BOOKED":
        raise errors.ApiError(errors.ERR_ORDER_APPOINTMENT_MISMATCH, 409,
                              "Appointment must be a BOOKED appointment of the same member.")

    subtotal, peak, total = retail_service.compute_totals(member["id"], lines, appt)
    rec = {
        "member_id": member["id"],
        "appointment_id": appt["id"],
        "lines": lines,
        "subtotal_cents": subtotal,
        "peak_surcharge_cents": peak,
        "total_cents": total,
        "status": "PAID",
    }
    stamp_create(rec)
    store.retail_orders[rec["id"]] = rec
    return success_object(serialize.retail_order_out(rec), status=201)


@bp.route("/retail-orders", methods=["GET"])
def list_retail_orders():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    appointment_id = request.args.get("appointment_id")
    items = list(store.retail_orders.values())
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if appointment_id is not None:
        items = [o for o in items if o["appointment_id"] == appointment_id]
    if role == "Member":
        items = [o for o in items if o["member_id"] == user_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.retail_order_out(o) for o in page], limit, offset, total)


@bp.route("/retail-orders/<oid>", methods=["GET"])
def get_retail_order(oid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    o = store.retail_orders.get(oid)
    if not o:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Retail order not found.")
    if role == "Member":
        ownership_member(role, user_id, o["member_id"])
    return success_object(serialize.retail_order_out(o))


@bp.route("/retail-orders/<oid>/void", methods=["POST"])
def void_retail_order(oid):
    _, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk"})
    o = store.retail_orders.get(oid)
    if not o:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_FOUND, 404, "Retail order not found.")
    o["status"] = "VOIDED"
    touch(o)
    return success_object(serialize.retail_order_out(o))
