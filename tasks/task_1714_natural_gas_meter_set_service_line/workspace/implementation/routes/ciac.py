"""CIACInvoice + CIACPayment endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVOICE_NOT_PAYABLE,
    ERR_INVOICE_NOT_REFUNDABLE,
    ERR_OVERPAYMENT,
    ERR_REFUND_AMOUNT_MISMATCH,
    ERR_SOD_PAYMENT_BY_ISSUER,
    ERR_SOD_REFUND_BY_PAYER,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_roles,
)
from response import success_list, success_object
from services.domain import (
    get_application,
    get_invoice,
    get_payment,
    payments_for_invoice,
    touch,
)

bp = Blueprint("ciac", __name__)


@bp.route("/ciac-invoices/<iid>", methods=["GET"])
def get_one_invoice(iid):
    require_roles(*ANY_ROLE)
    return success_object(get_invoice(iid))


@bp.route("/ciac-invoices", methods=["GET"])
def list_invoices():
    require_roles(*ANY_ROLE)
    records = list(db.ciac_invoices.values())
    me_id = request.args.get("main_extension_id")
    app_id = request.args.get("service_application_id")
    if me_id is not None:
        records = [i for i in records if i["main_extension_id"] == me_id]
    if app_id is not None:
        records = [i for i in records if i["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/ciac-invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    user_id, _ = require_roles("BillingClerk")
    invoice = get_invoice(iid)
    body = get_body()
    require_fields(body, "amount_cents", "method")
    amount = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", ("CHECK", "ACH", "CARD"))
    app = get_application(invoice["service_application_id"])
    check_app_mutable(app)
    # Entity state gate (7) → SoD (8) → fiscal (12)
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_error(ERR_INVOICE_NOT_PAYABLE, "Invoice is not payable in its current status")
    if user_id == invoice["issued_by_user_id"]:
        raise_error(ERR_SOD_PAYMENT_BY_ISSUER, "The invoice issuer may not record payments on it")
    balance = invoice["amount_due_cents"] - invoice["payments_applied_cents"]
    if amount > balance:
        raise_error(ERR_OVERPAYMENT, "Payment exceeds the balance due")

    invoice["payments_applied_cents"] += amount
    new_balance = invoice["amount_due_cents"] - invoice["payments_applied_cents"]
    invoice["balance_due_cents"] = new_balance
    fully_paid = amount == balance
    if fully_paid:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)
    now = db.now_iso()
    payment = {
        "id": new_id(),
        "ciac_invoice_id": invoice["id"],
        "direction": "PAYMENT",
        "amount_cents": amount,
        "method": method,
        "recorded_by_user_id": user_id,
        "created_at": now,
    }
    db.ciac_payments[payment["id"]] = payment
    # Bubble-up: application CIAC_PENDING → APPROVED_FOR_CONSTRUCTION on full payment
    if fully_paid and app["status"] == "CIAC_PENDING":
        app["status"] = "APPROVED_FOR_CONSTRUCTION"
        touch(app)
    return success_object(payment, 201)


@bp.route("/ciac-invoices/<iid>/refunds", methods=["POST"])
def record_refund(iid):
    user_id, _ = require_roles("BillingClerk")
    invoice = get_invoice(iid)
    body = get_body()
    require_fields(body, "amount_cents", "method")
    amount = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", ("CHECK", "ACH", "CARD"))
    app = get_application(invoice["service_application_id"])
    # Note: refund flow is specifically for REFUND_PENDING invoices which may sit
    # on terminal (cancelled/expired) applications — the unwind must remain payable,
    # so the terminal posture gate is not applied here.
    if invoice["status"] != "REFUND_PENDING":
        raise_error(ERR_INVOICE_NOT_REFUNDABLE, "Invoice is not refundable in its current status")
    for p in payments_for_invoice(invoice["id"], direction="PAYMENT"):
        if p["recorded_by_user_id"] == user_id:
            raise_error(ERR_SOD_REFUND_BY_PAYER, "A clerk who recorded a payment may not refund it")
    remaining = invoice["refund_required_cents"] - invoice["refunds_issued_cents"]
    if amount > remaining:
        raise_error(ERR_REFUND_AMOUNT_MISMATCH, "Refund exceeds the remaining required refund")

    invoice["refunds_issued_cents"] += amount
    if invoice["refunds_issued_cents"] == invoice["refund_required_cents"]:
        invoice["status"] = "REFUNDED"
    touch(invoice)
    now = db.now_iso()
    payment = {
        "id": new_id(),
        "ciac_invoice_id": invoice["id"],
        "direction": "REFUND",
        "amount_cents": amount,
        "method": method,
        "recorded_by_user_id": user_id,
        "created_at": now,
    }
    db.ciac_payments[payment["id"]] = payment
    return success_object(payment, 201)


@bp.route("/ciac-payments/<pid>", methods=["GET"])
def get_one_payment(pid):
    require_roles(*ANY_ROLE)
    return success_object(get_payment(pid))


@bp.route("/ciac-payments", methods=["GET"])
def list_payments():
    require_roles(*ANY_ROLE)
    records = list(db.ciac_payments.values())
    invoice_id = request.args.get("ciac_invoice_id")
    if invoice_id is not None:
        records = [p for p in records if p["ciac_invoice_id"] == invoice_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)
