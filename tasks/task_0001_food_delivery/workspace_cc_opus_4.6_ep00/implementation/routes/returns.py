from flask import Blueprint, request
from store import store
from models import make_unversioned, make_versioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_REFUND_AMOUNT_INVALID,
)

bp = Blueprint("returns", __name__)


@bp.route("/api/returns/<return_id>", methods=["GET"])
def get_return(return_id):
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "CustomerService"})
    ret = store.returns.get(return_id)
    if not ret:
        raise_error(ERR_NOT_FOUND, "Return not found")

    if request.user_role == "Customer":
        order = store.orders.get(ret["order_id"])
        if not order or order["customer_id"] != request.user_id:
            raise_error(ERR_FORBIDDEN, "Cannot view another customer's return")
    if request.user_role == "Restaurant":
        order = store.orders.get(ret["order_id"])
        if not order or order["restaurant_id"] != request.user_id:
            raise_error(ERR_FORBIDDEN, "Cannot view another restaurant's return")

    return success_response(serialize(ret))


@bp.route("/api/returns/<return_id>/approve", methods=["POST"])
def approve_return(return_id):
    check_role_permission({"CustomerService"})
    ret = store.returns.get(return_id)
    if not ret:
        raise_error(ERR_NOT_FOUND, "Return not found")

    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Return must be REQUESTED or ESCALATED to approve")

    order = store.orders.get(ret["order_id"])
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    data = request.get_json(force=True, silent=True) or {}
    approved_refund_cents = data.get("approved_refund_cents")
    if approved_refund_cents is None or not isinstance(approved_refund_cents, int):
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents is required")

    if approved_refund_cents < 1:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents must be >= 1")
    if approved_refund_cents > order["subtotal_cents"]:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents cannot exceed subtotal_cents")
    if approved_refund_cents > ret["requested_refund_cents"]:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "approved_refund_cents cannot exceed requested_refund_cents")

    ret["status"] = "APPROVED"
    ret["approved_refund_cents"] = approved_refund_cents
    ret["reviewer_cs_user_id"] = request.user_id
    touch(ret)

    order["status"] = "REFUNDED"
    if approved_refund_cents < order["subtotal_cents"]:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    else:
        order["payment_status"] = "FULLY_REFUNDED"
    touch(order)

    customer = store.customers.get(order["customer_id"])
    if customer:
        customer["credit_balance_cents"] += approved_refund_cents

        if customer["trust_score"] < 0.5 and ret["reason"] == "QUALITY_ISSUE":
            fine = make_unversioned({
                "subject_type": "CUSTOMER",
                "subject_id": customer["id"],
                "reason": "ABUSIVE_RETURN",
                "amount_cents": approved_refund_cents,
                "settlement_status": "PENDING",
                "order_id": order["id"],
            })
            store.fines[fine["id"]] = fine
            customer["credit_balance_cents"] -= approved_refund_cents

        touch(customer)

    restaurant = store.restaurants.get(order["restaurant_id"])
    if restaurant:
        restaurant["pending_settlement_cents"] -= approved_refund_cents
        touch(restaurant)

    return success_response(serialize(ret))


@bp.route("/api/returns/<return_id>/reject", methods=["POST"])
def reject_return(return_id):
    check_role_permission({"CustomerService"})
    ret = store.returns.get(return_id)
    if not ret:
        raise_error(ERR_NOT_FOUND, "Return not found")

    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Return must be REQUESTED or ESCALATED to reject")

    order = store.orders.get(ret["order_id"])
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    ret["status"] = "REJECTED"
    ret["reviewer_cs_user_id"] = request.user_id
    touch(ret)

    order["status"] = "DELIVERED"
    touch(order)

    return success_response(serialize(ret))


@bp.route("/api/returns/<return_id>/escalate", methods=["POST"])
def escalate_return(return_id):
    check_role_permission({"CustomerService"})
    ret = store.returns.get(return_id)
    if not ret:
        raise_error(ERR_NOT_FOUND, "Return not found")

    if ret["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Return must be REQUESTED to escalate")

    ret["status"] = "ESCALATED"
    touch(ret)

    wo = make_versioned({
        "opened_by_role": "CUSTOMER_SERVICE",
        "opened_by_id": request.user_id,
        "category": "OTHER",
        "related_order_id": ret["order_id"],
        "related_return_id": return_id,
        "assigned_cs_user_id": None,
        "resolution_notes": None,
        "status": "OPEN",
    })
    store.work_orders[wo["id"]] = wo

    return success_response(serialize(ret))


@bp.route("/api/returns/<return_id>/reopen", methods=["POST"])
def reopen_return(return_id):
    check_role_permission({"CustomerService"})
    ret = store.returns.get(return_id)
    if not ret:
        raise_error(ERR_NOT_FOUND, "Return not found")

    if ret["status"] != "ESCALATED":
        raise_error(ERR_INVALID_STATE, "Return must be ESCALATED to reopen")

    ret["status"] = "REQUESTED"
    touch(ret)

    for wo in store.work_orders.values():
        if wo.get("related_return_id") == return_id and wo["status"] != "CLOSED":
            wo["status"] = "CLOSED"
            touch(wo)

    return success_response(serialize(ret))
