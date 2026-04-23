from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from response import success_response
from errors import (raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
                    ERR_REFUND_AMOUNT_INVALID, ERR_VALIDATION)
from services.fine_service import create_abusive_return_fine
from models.work_order import WorkOrder

bp = Blueprint("returns", __name__)


def get_return_or_404(return_id):
    r = db.returns.get(return_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Return not found.")
    return r


@bp.route("/api/returns/<return_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
def get_return(return_id):
    r = get_return_or_404(return_id)
    return success_response(r.to_dict())


@bp.route("/api/returns/<return_id>/approve", methods=["POST"])
@require_roles("CustomerService")
def approve_return(return_id):
    r = get_return_or_404(return_id)
    if r.status not in ("REQUESTED", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Return must be in REQUESTED or ESCALATED state.")

    data = request.get_json(force=True, silent=True) or {}
    approved_refund_cents = data.get("approved_refund_cents")

    order = db.orders.get(r.order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found.")

    if approved_refund_cents is None or not isinstance(approved_refund_cents, int):
        raise_error(ERR_VALIDATION, "approved_refund_cents is required and must be an integer.")
    if approved_refund_cents < 1:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents must be at least 1.")
    if approved_refund_cents > order.subtotal_cents:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents exceeds subtotal.")
    if approved_refund_cents > r.requested_refund_cents:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents exceeds requested amount.")

    r.status = "APPROVED"
    r.approved_refund_cents = approved_refund_cents
    r.reviewer_cs_user_id = request.user_id
    r.touch()

    order.status = "REFUNDED"
    if approved_refund_cents == order.subtotal_cents:
        order.payment_status = "FULLY_REFUNDED"
    else:
        order.payment_status = "PARTIALLY_REFUNDED"
    order.touch()

    customer = db.customers.get(order.customer_id)
    if customer:
        customer.credit_balance_cents += approved_refund_cents
        customer.touch()

    restaurant = db.restaurants.get(order.restaurant_id)
    if restaurant:
        restaurant.pending_settlement_cents -= approved_refund_cents
        restaurant.touch()

    if customer and customer.trust_score < 0.5 and r.reason == "QUALITY_ISSUE":
        create_abusive_return_fine(customer, approved_refund_cents)

    return success_response(r.to_dict())


@bp.route("/api/returns/<return_id>/reject", methods=["POST"])
@require_roles("CustomerService")
def reject_return(return_id):
    r = get_return_or_404(return_id)
    if r.status not in ("REQUESTED", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Return must be in REQUESTED or ESCALATED state.")

    r.status = "REJECTED"
    r.reviewer_cs_user_id = request.user_id
    r.touch()

    order = db.orders.get(r.order_id)
    if order:
        order.status = "DELIVERED"
        order.touch()

    return success_response(r.to_dict())


@bp.route("/api/returns/<return_id>/escalate", methods=["POST"])
@require_roles("CustomerService")
def escalate_return(return_id):
    r = get_return_or_404(return_id)
    if r.status != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Return must be in REQUESTED state to escalate.")

    r.status = "ESCALATED"
    r.touch()

    wo = WorkOrder(
        opened_by_role="CUSTOMER_SERVICE",
        opened_by_id=request.user_id,
        category="OTHER",
        related_return_id=r.id,
        related_order_id=r.order_id,
    )
    wo.status = "OPEN"
    db.work_orders[wo.id] = wo

    return success_response(r.to_dict())


@bp.route("/api/returns/<return_id>/reopen", methods=["POST"])
@require_roles("CustomerService")
def reopen_return(return_id):
    r = get_return_or_404(return_id)
    if r.status != "ESCALATED":
        raise_error(ERR_INVALID_STATE, "Return must be in ESCALATED state to reopen.")

    r.status = "REQUESTED"
    r.touch()

    for wo in db.work_orders.values():
        if wo.related_return_id == r.id and wo.status != "CLOSED":
            wo.status = "CLOSED"
            wo.touch()

    return success_response(r.to_dict())
