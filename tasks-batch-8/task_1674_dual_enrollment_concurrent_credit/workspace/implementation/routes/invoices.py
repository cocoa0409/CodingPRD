"""Invoice / Payment / refund endpoints (PRD 3.7).

Invoice state machine: ISSUED -> PARTIALLY_PAID -> PAID (payment-driven), and
ISSUED|PARTIALLY_PAID|PAID -> VOIDED (system, at refund_pct == 100). The
refund_status axis (NONE -> DUE -> PROCESSED) is independent of status.
"""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_INVOICE_INVALID_STATE,
    ERR_OVERPAYMENT,
    ERR_REFUND_NOT_DUE,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calculations import paid_total_cents, settle_refund
from services.core import new_record, public, touch
from validate import get_body, opt_str, req_enum, req_int, require_path_resource

bp = Blueprint("invoices", __name__)

PAYERS = {"STATE", "DISTRICT", "FAMILY"}
PAYABLE_STATUSES = {"ISSUED", "PARTIALLY_PAID"}


@bp.get("/invoices")
def list_invoices():
    return list_response(
        "invoices",
        {
            "enrollment_id": arg("enrollment_id"),
            "funding_agreement_id": arg("funding_agreement_id"),
            "status": arg("status"),
        },
    )


@bp.get("/invoices/<rid>")
def get_invoice(rid):
    return get_one("invoices", rid)


@bp.post("/invoices/<rid>/payments")
def record_payment(rid):
    authorized(["Bursar"])
    body = get_body()
    payer = req_enum(body, "payer", PAYERS)
    amount_cents = req_int(body, "amount_cents", minimum=1)
    note = opt_str(body, "note")
    invoice = require_path_resource("invoices", rid)

    # Priority 6: a VOIDED (or otherwise settled) invoice cannot take payments.
    if invoice["status"] not in PAYABLE_STATUSES:
        raise_error(
            ERR_INVOICE_INVALID_STATE,
            "payments require the invoice to be ISSUED or PARTIALLY_PAID",
        )
    # Priority 16: payment must not exceed the payer's remaining billed share.
    paid_field = f"paid_{payer.lower()}_cents"
    share_field = f"{payer.lower()}_amount_cents"
    if invoice[paid_field] + amount_cents > invoice[share_field]:
        raise_error(
            ERR_OVERPAYMENT,
            "payment exceeds the payer's remaining share on the invoice",
        )

    payment = new_record(
        "payments",
        {
            "invoice_id": invoice["id"],
            "payer": payer,
            "amount_cents": amount_cents,
            "note": note,
        },
    )
    invoice[paid_field] += amount_cents
    total = paid_total_cents(invoice)
    if total >= invoice["tuition_total_cents"]:
        invoice["status"] = "PAID"
    elif total > 0:
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)
    return success_object(public(payment), status=201)


@bp.get("/payments")
def list_payments():
    return list_response(
        "payments",
        {"invoice_id": arg("invoice_id"), "payer": arg("payer")},
    )


@bp.get("/payments/<rid>")
def get_payment(rid):
    return get_one("payments", rid)


@bp.post("/invoices/<rid>/refund")
def process_refund(rid):
    authorized(["Bursar"])
    invoice = require_path_resource("invoices", rid)
    # Priority 16: refund requires refund_status == DUE (a second refund call
    # on an already-PROCESSED invoice fails the same way).
    if invoice["refund_status"] != "DUE":
        raise_error(ERR_REFUND_NOT_DUE, "no refund is due on this invoice")
    settle_refund(invoice)  # settled variant: computed from PAID amounts
    return success_object(public(invoice))
