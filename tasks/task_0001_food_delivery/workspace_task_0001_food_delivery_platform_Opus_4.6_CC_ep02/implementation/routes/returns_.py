from flask import Blueprint, request
from auth import require_roles
from errors import APIError
from models import (returns as returns_store, orders, customers, restaurants,
                    fines, work_orders, operational_resource_base, versioned_resource_base,
                    touch, check_version)
from response_envelope import success_response
from calculations import recompute_rider_bonus
import clock

bp = Blueprint("returns", __name__)


def return_dict(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "requested_refund_cents": r["requested_refund_cents"],
        "approved_refund_cents": r["approved_refund_cents"],
        "reviewer_cs_user_id": r["reviewer_cs_user_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/returns/<return_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
def get_return(return_id):
    ret = returns_store.get(return_id)
    if not ret:
        raise APIError("ERR_NOT_FOUND", "Return not found")
    return success_response(return_dict(ret))


@bp.route("/api/returns/<return_id>/approve", methods=["POST"])
@require_roles("CustomerService")
def approve_return(return_id):
    ret = returns_store.get(return_id)
    if not ret:
        raise APIError("ERR_NOT_FOUND", "Return not found")

    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise APIError("ERR_INVALID_STATE", "Return must be in REQUESTED or ESCALATED to approve")

    order = orders.get(ret["order_id"])
    if not order:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    data = request.get_json(force=True, silent=True) or {}

    approved_refund_cents = data.get("approved_refund_cents")
    if approved_refund_cents is None or not isinstance(approved_refund_cents, int):
        raise APIError("ERR_VALIDATION", "approved_refund_cents must be an integer")

    if (approved_refund_cents < 1
            or approved_refund_cents > order["subtotal_cents"]
            or approved_refund_cents > ret["requested_refund_cents"]):
        raise APIError("ERR_REFUND_AMOUNT_INVALID",
                        "approved_refund_cents must be between 1 and min(subtotal_cents, requested_refund_cents)")

    check_version(ret, data.get("version"))

    ret["status"] = "APPROVED"
    ret["approved_refund_cents"] = approved_refund_cents
    ret["reviewer_cs_user_id"] = request.user_id
    touch(ret)

    order["status"] = "REFUNDED"
    if approved_refund_cents == order["subtotal_cents"]:
        order["payment_status"] = "FULLY_REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    touch(order)

    customer = customers.get(order["customer_id"])
    if customer:
        customer["credit_balance_cents"] += approved_refund_cents
        touch(customer)

    restaurant = restaurants.get(order["restaurant_id"])
    if restaurant:
        restaurant["pending_settlement_cents"] -= approved_refund_cents
        touch(restaurant)

    if customer and customer["trust_score"] < 0.5 and ret["reason"] == "QUALITY_ISSUE":
        fine = operational_resource_base()
        fine.update({
            "subject_type": "CUSTOMER",
            "subject_id": customer["id"],
            "reason": "ABUSIVE_RETURN",
            "amount_cents": approved_refund_cents,
            "settlement_status": "PENDING",
            "order_id": order["id"],
        })
        fines[fine["id"]] = fine

    return success_response(return_dict(ret))


@bp.route("/api/returns/<return_id>/reject", methods=["POST"])
@require_roles("CustomerService")
def reject_return(return_id):
    ret = returns_store.get(return_id)
    if not ret:
        raise APIError("ERR_NOT_FOUND", "Return not found")

    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise APIError("ERR_INVALID_STATE", "Return must be in REQUESTED or ESCALATED to reject")

    data = request.get_json(force=True, silent=True) or {}
    check_version(ret, data.get("version"))

    order = orders.get(ret["order_id"])

    ret["status"] = "REJECTED"
    ret["reviewer_cs_user_id"] = request.user_id
    touch(ret)

    if order and order["status"] == "REFUND_REQUESTED":
        order["status"] = "DELIVERED"
        touch(order)

    return success_response(return_dict(ret))


@bp.route("/api/returns/<return_id>/escalate", methods=["POST"])
@require_roles("CustomerService")
def escalate_return(return_id):
    ret = returns_store.get(return_id)
    if not ret:
        raise APIError("ERR_NOT_FOUND", "Return not found")

    if ret["status"] != "REQUESTED":
        raise APIError("ERR_INVALID_STATE", "Return must be in REQUESTED to escalate")

    ret["status"] = "ESCALATED"
    touch(ret)

    wo = versioned_resource_base()
    wo.update({
        "opened_by_role": "CUSTOMER_SERVICE",
        "opened_by_id": request.user_id,
        "category": "OTHER",
        "related_order_id": ret["order_id"],
        "related_return_id": ret["id"],
        "assigned_cs_user_id": None,
        "resolution_notes": None,
        "status": "OPEN",
    })
    work_orders[wo["id"]] = wo

    return success_response(return_dict(ret))


@bp.route("/api/returns/<return_id>/reopen", methods=["POST"])
@require_roles("CustomerService")
def reopen_return(return_id):
    ret = returns_store.get(return_id)
    if not ret:
        raise APIError("ERR_NOT_FOUND", "Return not found")

    if ret["status"] != "ESCALATED":
        raise APIError("ERR_INVALID_STATE", "Return must be in ESCALATED to reopen")

    ret["status"] = "REQUESTED"
    touch(ret)

    for wo in work_orders.values():
        if wo.get("related_return_id") == return_id and wo["status"] != "CLOSED":
            wo["status"] = "CLOSED"
            touch(wo)

    return success_response(return_dict(ret))
