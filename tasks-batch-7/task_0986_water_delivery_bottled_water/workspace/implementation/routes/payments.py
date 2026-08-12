"""Payment endpoints."""
from flask import Blueprint

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_enum, f_int, f_str,
                        require_owner, require_roles)
from response import ok_object
from services import base_record, bump, ser_payment

bp = Blueprint("payments", __name__)

PAYMENT_METHODS = {"CARD", "ACH", "CHECK", "CREDIT_MEMO"}
PAYMENT_TERMINAL = ("APPLIED", "FAILED", "REFUNDED")
APPLIABLE_INVOICE_STATES = ("OPEN", "OVERDUE", "PARTIALLY_PAID", "DISPUTED")


def _get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise errors.not_found("payment not found")
    return p


@bp.post("/payments")
@require_roles("BillingAdmin", "CustomerSelf")
def create_payment():
    d = body_json()
    invoice_id = f_str(d, "invoice_id")
    amount_cents = f_int(d, "amount_cents", min_value=1)
    method = f_enum(d, "method", PAYMENT_METHODS)
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise errors.invalid_reference("invoice_id does not resolve")
    require_owner(inv["customer_id"])
    rec = base_record()
    rec.update({
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": method,
        "payment_status": "PENDING",
        "applied_at": None,
    })
    with db.lock:
        db.payments[rec["id"]] = rec
    return ok_object(ser_payment(rec), 201)


@bp.get("/payments/<pid>")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def get_payment(pid):
    p = _get_payment(pid)
    inv = db.invoices.get(p["invoice_id"])
    if inv is not None:
        require_owner(inv["customer_id"])
    return ok_object(ser_payment(p))


@bp.post("/payments/<pid>/apply")
@require_roles("BillingAdmin")
def apply_payment(pid):
    p = _get_payment(pid)
    check_transition(p, "payment_status", ("PENDING",), PAYMENT_TERMINAL,
                     "Payment")
    inv = db.invoices.get(p["invoice_id"])
    if inv is None or inv["invoice_status"] not in APPLIABLE_INVOICE_STATES:
        raise errors.invalid_state(
            "invoice is not in a state that accepts payment application")
    if p["amount_cents"] > inv["balance_due_cents"]:
        raise errors.ApiError(errors.ERR_OVERPAYMENT, 422,
                              "payment amount exceeds invoice balance due")
    with db.lock:
        p["payment_status"] = "APPLIED"
        p["applied_at"] = services.now()
        bump(p)
        inv["balance_due_cents"] -= p["amount_cents"]
        if inv["balance_due_cents"] == 0:
            inv["invoice_status"] = "PAID"
        elif inv["invoice_status"] in ("OPEN", "OVERDUE"):
            inv["invoice_status"] = "PARTIALLY_PAID"
        bump(inv)
        if inv["invoice_status"] == "PAID":
            customer = db.customers.get(inv["customer_id"])
            if customer is not None:
                services.maybe_clear_overdue_since(customer)
    return ok_object(ser_payment(p))


@bp.post("/payments/<pid>/mark-failed")
@require_roles("BillingAdmin")
def mark_failed_payment(pid):
    p = _get_payment(pid)
    check_transition(p, "payment_status", ("PENDING",), PAYMENT_TERMINAL,
                     "Payment")
    with db.lock:
        p["payment_status"] = "FAILED"
        bump(p)
    return ok_object(ser_payment(p))


@bp.post("/payments/<pid>/refund")
@require_roles("BillingAdmin")
def refund_payment(pid):
    p = _get_payment(pid)
    check_transition(p, "payment_status", ("APPLIED",), PAYMENT_TERMINAL,
                     "Payment")
    inv = db.invoices.get(p["invoice_id"])
    if inv is None or inv["invoice_status"] != "PAID":
        raise errors.invalid_state(
            "refund requires the invoice to be PAID")
    with db.lock:
        p["payment_status"] = "REFUNDED"
        bump(p)
        inv["balance_due_cents"] += p["amount_cents"]
        inv["invoice_status"] = "OPEN"
        bump(inv)
    return ok_object(ser_payment(p))
