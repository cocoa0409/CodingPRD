"""Payment: capture, fetch, refund (PRD 3.7)."""
from flask import Blueprint, g

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import calculations as C
from services import helpers as H

bp = Blueprint("payments", __name__)


@bp.route("/payments", methods=["POST"])
@require_roles("ServiceAdvisor", "Customer")
def create_payment():
    body = V.get_json()
    work_order_id = V.require_str(body, "work_order_id")
    wo = H.get_work_order(work_order_id)
    # Ownership: a Customer may only pay against their own work order.
    H.enforce_work_order_owner(wo)

    amount_cents = V.require_int(body, "amount_cents")
    method = V.require_enum(body, "method", {"CARD", "CASH", "INSURANCE"})
    if amount_cents < 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "amount_cents must be >= 1.")

    # Overpayment check (priority 15): would push amount_paid above total_charge.
    if wo["amount_paid_cents"] + amount_cents > wo["total_charge_cents"]:
        raise ApiError(errors.ERR_OVERPAYMENT, 422, "Payment would exceed the total charge.")

    pay = db.stamp_new({
        "work_order_id": work_order_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "CAPTURED",
        "refunded_amount_cents": 0,
    })
    db.payments[pay["id"]] = pay
    # Recompute the work order aggregate (bumps work order version per PRD 2.4).
    H.recompute_amount_paid(wo)
    db.touch(wo)
    return response.success(H.view(pay), 201)


@bp.route("/payments/<pid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def get_payment(pid):
    pay = H.get_payment(pid)
    if g.role == "Customer":
        wo = db.work_orders.get(pay["work_order_id"])
        if wo is not None:
            H.enforce_work_order_owner(wo)
    return response.success(H.view(pay))


@bp.route("/payments/<pid>/refund", methods=["POST"])
@require_roles("ShopManager")
def refund_payment(pid):
    pay = H.get_payment(pid)
    if pay["status"] != "CAPTURED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Payment is not CAPTURED.")
    wo = db.work_orders.get(pay["work_order_id"])

    refunded = C.refund_amount(pay["amount_cents"], wo["status"], wo["service_decision"])
    pay["refunded_amount_cents"] = refunded
    pay["status"] = "REFUNDED"
    db.touch(pay)
    # Recompute work order aggregate, preserving the ledger invariant.
    H.recompute_amount_paid(wo)
    db.touch(wo)
    return response.success(H.view(pay))
