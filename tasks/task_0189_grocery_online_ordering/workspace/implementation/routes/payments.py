"""Payment + Refund discovery endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import err, ERR_VALIDATION  # noqa: F401
from errors import ApiError
from middleware import get_user_context, require_role
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("payments", __name__)

# Local not-found specs (no dedicated error_id is catalogued for payment/refund
# id misses; PRD §2.7 only enumerates store/customer/product/slot/picker/order/
# line/substitution. We use ERR_VALIDATION 404 fallback via a generic message
# only when needed — but payments/refunds are id-bearing GETs, so on a miss we
# return the closest catalogued behaviour: a 404 with a generic error_id.)
_NOT_FOUND_PAYMENT = ("ERR_VALIDATION", 404)
_NOT_FOUND_REFUND = ("ERR_VALIDATION", 404)


@bp.route("/v1/payments", methods=["GET"])
def list_payments():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    limit, offset = get_pagination()
    order_id = request.args.get("order_id")
    with db.lock:
        records = list(db.payments.values())
        if order_id is not None:
            records = [p for p in records if p["order_id"] == order_id]
        if role == "Customer":
            owned = {o["id"] for o in db.orders.values() if o["customer_id"] == user_id}
            records = [p for p in records if p["order_id"] in owned]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    with db.lock:
        payment = db.payments.get(payment_id)
        if payment is None:
            raise ApiError(_NOT_FOUND_PAYMENT[0], _NOT_FOUND_PAYMENT[1], "Payment not found")
        return object_response(public(payment))


@bp.route("/v1/refunds", methods=["GET"])
def list_refunds():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    limit, offset = get_pagination()
    order_id = request.args.get("order_id")
    order_line_id = request.args.get("order_line_id")
    with db.lock:
        records = list(db.refunds.values())
        if order_id is not None:
            records = [r for r in records if r["order_id"] == order_id]
        if order_line_id is not None:
            records = [r for r in records if r["order_line_id"] == order_line_id]
        if role == "Customer":
            owned = {o["id"] for o in db.orders.values() if o["customer_id"] == user_id}
            records = [r for r in records if r["order_id"] in owned]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/refunds/<refund_id>", methods=["GET"])
def get_refund(refund_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    with db.lock:
        refund = db.refunds.get(refund_id)
        if refund is None:
            raise ApiError(_NOT_FOUND_REFUND[0], _NOT_FOUND_REFUND[1], "Refund not found")
        return object_response(public(refund))
