"""Payment endpoints (PRD §3.5)."""
from decimal import Decimal

from flask import Blueprint

import errors
import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import calc, domain
from routes.orders import find_order_or_404, assert_customer_owns_order, _emit_notification

bp = Blueprint("payments", __name__)

PAYMENT_KINDS = {"DEPOSIT", "BALANCE"}


def _find_payment_or_404(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        errors.raise_err(errors.ERR_PAYMENT_NOT_FOUND, "Payment not found")
    return p


def _amount_two_dp(amount):
    if not validate.is_number(amount) or amount <= 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "amount must be a positive number")
    # enforce at most 2 decimal places
    d = Decimal(str(amount))
    if d != d.quantize(Decimal("0.01")):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "amount must have at most 2 decimal places")
    return amount


@bp.route("/framing-orders/<order_id>/payments", methods=["POST"])
def apply_payment(order_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk",))
    o = find_order_or_404(order_id)
    body = validate.get_json_body()

    kind = validate.as_enum(validate.require(body, "kind"), "kind", PAYMENT_KINDS)
    amount = _amount_two_dp(validate.require(body, "amount"))

    customer = db.customers[o["customer_id"]]

    if kind == "DEPOSIT":
        # state: order must be QUOTED
        if o["production_status"] != "QUOTED":
            errors.raise_err(errors.ERR_NOT_QUOTED, "Order is not quoted")
        # fiscal: amount >= deposit_required
        if calc.D(amount) < calc.D(o["deposit_required"]):
            errors.raise_err(errors.ERR_DEPOSIT_TOO_LOW, "Deposit amount too low")

        p = _create_payment(order_id, "DEPOSIT", amount)
        domain.recompute_ledger(o)
        o["payment_status"] = "DEPOSIT_PAID"
        domain.touch(o)

        _emit_notification(o, customer, kind="DEPOSIT_RECEIPT")
        return ok_object(domain.serialize_payment(p), status=201)

    else:  # BALANCE
        # fiscal: after applying, amount_paid >= effective_total
        applied = domain.order_payments_applied_sorted(order_id)
        # simulate adding this payment
        current_paid, _ = calc.order_ledger(applied, o["estimate_total"], o["final_invoice_total"])
        new_paid = current_paid + calc.D(amount)
        fin = calc.D(o["final_invoice_total"])
        effective_total = fin if fin > 0 else calc.D(o["estimate_total"])
        if new_paid < effective_total:
            errors.raise_err(errors.ERR_PAYMENT_INSUFFICIENT, "Balance payment insufficient")

        p = _create_payment(order_id, "BALANCE", amount)
        domain.recompute_ledger(o)
        o["payment_status"] = "PAID_IN_FULL"
        domain.touch(o)
        return ok_object(domain.serialize_payment(p), status=201)


def _create_payment(order_id, kind, amount):
    p = {
        "order_id": order_id,
        "kind": kind,
        "amount": amount,
        "payment_status": "APPLIED",
    }
    domain.stamp_create(p)
    db.payments[p["id"]] = p
    return p


@bp.route("/framing-orders/<order_id>/payments", methods=["GET"])
def list_order_payments(order_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "Customer"))
    o = find_order_or_404(order_id)
    assert_customer_owns_order(auth, o)
    limit, offset = validate.parse_pagination()
    items = [p for p in db.payments.values() if p["order_id"] == order_id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_payment(p) for p in page], limit, offset, total)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "Customer"))
    p = _find_payment_or_404(payment_id)
    if auth.role == "Customer":
        o = db.framing_orders.get(p["order_id"])
        if o is None or auth.user_id != o["customer_id"]:
            errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Customer may only access own payment")
    return ok_object(domain.serialize_payment(p))
