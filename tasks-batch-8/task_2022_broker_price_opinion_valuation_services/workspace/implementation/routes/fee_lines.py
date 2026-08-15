"""Fee line endpoints (PRD 3.5)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import allowed
from response import success_object, success_list
from serializers import ser_fee_line
from routes.orders import get_order_or_404, TERMINAL_STATES
from validation import body, req_str, req_enum, sort_and_page

bp = Blueprint("fee_lines", __name__)

FEE_KINDS = {"BASE", "RUSH_SURCHARGE", "INTERIOR_SURCHARGE", "APPRAISAL_SURCHARGE", "TRAVEL", "MISC"}


def _get_fee_or_404(order_id: str, fee_id: str) -> dict:
    fee = db.fee_lines.get(fee_id)
    if fee is None or fee["order_id"] != order_id:
        raise ApiError(ERR_NOT_FOUND, f"FeeLine {fee_id} not found on order {order_id}", 404)
    return fee


@bp.post("/bpo/valuation-orders/<order_id>/fee-lines")
@allowed("Broker", "OperationsManager", "BillingClerk")
def create_fee_line(user_id, role, order_id):
    order = get_order_or_404(order_id)
    b = body()
    if order["fulfillment_status"] in TERMINAL_STATES:
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']} (terminal)", 409)
    fee_kind = req_enum(b, "fee_kind", FEE_KINDS)
    description = req_str(b, "description", allow_empty=True)
    amount = b.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'amount_cents': required integer", 400)

    record = db.stamp_new({
        "id": db.new_id(),
        "order_id": order_id,
        "fee_kind": fee_kind,
        "description": description,
        "amount_cents": amount,
        "status": "DRAFT",
    })
    db.fee_lines[record["id"]] = record
    return success_object(ser_fee_line(record), 201)


@bp.get("/bpo/valuation-orders/<order_id>/fee-lines")
@allowed("Broker", "OperationsManager", "BillingClerk", "QCReviewer", "PlatformAdmin", "ClientAdmin")
def list_fee_lines(user_id, role, order_id):
    get_order_or_404(order_id)
    records = [f for f in db.fee_lines.values() if f["order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_fee_line)
    return success_list(items, limit, offset, total)


@bp.post("/bpo/valuation-orders/<order_id>/fee-lines/<fee_id>/confirm")
@allowed("BillingClerk", "OperationsManager")
def confirm_fee_line(user_id, role, order_id, fee_id):
    get_order_or_404(order_id)
    fee = _get_fee_or_404(order_id, fee_id)
    if fee["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"FeeLine is {fee['status']}, expected DRAFT", 409)
    fee["status"] = "CONFIRMED"
    db.touch(fee)
    return success_object(ser_fee_line(fee))


@bp.post("/bpo/valuation-orders/<order_id>/fee-lines/<fee_id>/cancel")
@allowed("BillingClerk", "OperationsManager")
def cancel_fee_line(user_id, role, order_id, fee_id):
    get_order_or_404(order_id)
    fee = _get_fee_or_404(order_id, fee_id)
    if fee["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"FeeLine is {fee['status']}, expected DRAFT", 409)
    fee["status"] = "CANCELLED"
    db.touch(fee)
    return success_object(ser_fee_line(fee))
