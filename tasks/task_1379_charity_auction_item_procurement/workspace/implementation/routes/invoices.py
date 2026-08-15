"""Invoice, Payment, and payment-simulation routes (PRD 3.6, 3.7, 3.8)."""

from flask import Blueprint, request

import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("invoices", __name__)

READ = mw.ALL_ROLES


@bp.get("/invoices/<rid>")
def get_invoice(rid):
    mw.require_auth(READ)
    return response.success_object(wf.serialize_invoice(mw.get_or_404("invoices", rid)))


@bp.get("/invoices")
def list_invoices():
    mw.require_auth(READ)
    limit, offset = mw.parse_pagination()
    items = list(stores["invoices"].values())
    for f in ("gala_event_id", "bidder_id", "bundle_id", "payment_status"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if str(i.get(f)) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([wf.serialize_invoice(i) for i in page], limit, offset, total)


@bp.post("/invoices/<rid>/payments")
def create_payment(rid):
    user_id, _ = mw.require_auth(["Bidder"])
    invoice = mw.get_or_404("invoices", rid)
    # Ownership (priority 3): only the invoice's winning bidder may pay it.
    if invoice["bidder_id"] != user_id:
        raise errors.err_ownership("Only the invoice's winning bidder may pay it")
    body = mw.get_json_body()
    amount_cents = mw.require_int(body, "amount_cents")
    method = mw.require_enum(body, "method", {"CARD", "CHECK"})
    if invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise errors.err_invoice_not_payable()
    outstanding = invoice["winning_bid_cents"] - wf.invoice_amount_paid(invoice["id"])
    if amount_cents < 1 or amount_cents > outstanding:
        raise errors.err_payment_exceeds_balance(
            f"amount_cents must be within 1..{outstanding}"
        )
    rec = mw.new_record()
    rec["invoice_id"] = invoice["id"]
    rec["amount_cents"] = amount_cents
    rec["method"] = method
    rec["status"] = "INITIATED"
    stores["payments"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/invoices/<rid>/payments")
def list_invoice_payments(rid):
    mw.require_auth(READ)
    invoice = mw.get_or_404("invoices", rid)
    limit, offset = mw.parse_pagination()
    items = [p for p in stores["payments"].values() if p["invoice_id"] == invoice["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(p) for p in page], limit, offset, total)


@bp.post("/_payments/simulate")
def simulate_payment():
    mw.require_auth(["GalaAdmin"])
    body = mw.get_json_body()
    payment_id = mw.require_string(body, "payment_id")
    payment = mw.get_or_404("payments", payment_id)
    outcome = mw.require_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    if payment["status"] != "INITIATED":
        raise errors.err_invalid_state("Only INITIATED payments can be settled")
    if outcome == "FAILED":
        # No invoice mutation; a fresh payment may be created afterwards.
        payment["status"] = "FAILED"
        mw.touch(payment)
        return response.success_object(mw.serialize(payment))
    payment["status"] = "SUCCEEDED"
    mw.touch(payment)
    invoice = stores["invoices"][payment["invoice_id"]]
    paid = wf.invoice_amount_paid(invoice["id"])
    if paid >= invoice["winning_bid_cents"]:
        if invoice["payment_status"] != "PAID":
            wf.paid_cascade(invoice)
    elif paid > 0 and invoice["payment_status"] == "UNPAID":
        invoice["payment_status"] = "PARTIALLY_PAID"
        mw.touch(invoice)
    return response.success_object(mw.serialize(payment))


@bp.post("/invoices/<rid>/refund")
def refund_invoice(rid):
    mw.require_auth(["FinanceOfficer"])
    invoice = mw.get_or_404("invoices", rid)
    cert = wf.certificate_of(invoice["id"])
    if invoice["payment_status"] != "PAID":
        raise errors.err_refund_forbidden("Refund requires payment_status PAID")
    if cert is not None and cert["status"] == "REDEEMED":
        raise errors.err_refund_forbidden("Redeemed experiences cannot be refunded")
    wf.refund_cascade(invoice)
    return response.success_object(wf.serialize_invoice(invoice))


@bp.post("/invoices/<rid>/write-off")
def writeoff_invoice(rid):
    mw.require_auth(["FinanceOfficer"])
    invoice = mw.get_or_404("invoices", rid)
    if invoice["payment_status"] != "UNPAID":
        raise errors.err_writeoff_forbidden("Write-off requires payment_status UNPAID")
    wf.writeoff_cascade(invoice)
    return response.success_object(wf.serialize_invoice(invoice))


@bp.post("/invoices/<rid>/fulfill")
def fulfill_invoice(rid):
    mw.require_auth(["GalaAdmin"])
    invoice = mw.get_or_404("invoices", rid)
    if invoice["payment_status"] != "PAID":
        raise errors.err_invalid_state("Fulfillment requires payment_status PAID")
    if invoice["fulfillment_status"] != "READY":
        raise errors.err_invalid_state("Fulfillment requires fulfillment_status READY")
    invoice["fulfillment_status"] = "FULFILLED"
    mw.touch(invoice)
    wf.settle_bundle_bubble(invoice)
    return response.success_object(wf.serialize_invoice(invoice))


@bp.get("/invoices/<rid>/certificates")
def list_invoice_certificates(rid):
    mw.require_auth(READ)
    invoice = mw.get_or_404("invoices", rid)
    limit, offset = mw.parse_pagination()
    items = [c for c in stores["certificates"].values() if c["invoice_id"] == invoice["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(c) for c in page], limit, offset, total)
