"""Invoices, collection and speaker remittances (PRD §3.7)."""

from flask import Blueprint

import db
import errors
import validators as v
from errors import fail
from middleware import get_invoice, get_remittance, own_invoice, roles
from response import ok, paged
from services import lifecycle
from store import public, touch
from timeutil import fmt_iso

bp = Blueprint("money", __name__)


# --- invoices ---------------------------------------------------------------

@bp.get("/invoices")
@roles("BureauAdmin", "BookingAgent", "Client")
def list_invoices():
    engagement_id = v.query_string("engagement_id")
    client_id = v.query_string("client_id")
    kind = v.query_string("kind")
    status = v.query_string("status")
    rows = []
    for row in db.invoices.values():
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        if client_id is not None and row["client_id"] != client_id:
            continue
        if kind is not None and row["kind"] != kind:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/invoices/<invoice_id>")
@roles("BureauAdmin", "BookingAgent", "Client")
def read_invoice(invoice_id):
    return ok(public(get_invoice(invoice_id)))


@bp.post("/invoices/<invoice_id>/payments")
@roles("Client", "BureauAdmin")
def pay_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    data = v.body()
    amount = v.req_cents(data, "amount_cents")
    v.opt_string(data, "method")

    own_invoice(invoice)

    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        fail(errors.ERR_INVOICE_NOT_PAYABLE)

    remaining = invoice["amount_due_cents"] - invoice["amount_paid_cents"]
    if amount <= 0 or amount > remaining:
        fail(errors.ERR_OVERPAYMENT)

    invoice["amount_paid_cents"] = invoice["amount_paid_cents"] + amount
    settled = amount == remaining
    invoice["status"] = "PAID" if settled else "PARTIALLY_PAID"
    touch(invoice)

    client = db.clients[invoice["client_id"]]
    client["outstanding_balance_cents"] = client["outstanding_balance_cents"] - amount
    touch(client)

    engagement = db.engagements[invoice["engagement_id"]]
    engagement["settlement_status"] = "COLLECTED" if settled else "PARTIALLY_COLLECTED"
    touch(engagement)

    if settled:
        remittance = lifecycle.remittance_of_engagement(engagement["id"], ("PENDING",))
        if remittance is not None:
            remittance["status"] = "APPROVED"
            touch(remittance)
    return ok(public(invoice))


@bp.post("/invoices/<invoice_id>/void")
@roles("BureauAdmin")
def void_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    data = v.body()
    v.opt_string(data, "void_reason")

    own_invoice(invoice)

    if invoice["status"] != "ISSUED":
        fail(errors.ERR_INVOICE_NOT_PAYABLE)

    outstanding = invoice["amount_due_cents"] - invoice["amount_paid_cents"]
    invoice["status"] = "VOID"
    touch(invoice)

    client = db.clients[invoice["client_id"]]
    client["outstanding_balance_cents"] = client["outstanding_balance_cents"] - outstanding
    touch(client)

    engagement = db.engagements[invoice["engagement_id"]]
    engagement["settlement_status"] = "WRITTEN_OFF"
    touch(engagement)

    remittance = lifecycle.remittance_of_engagement(engagement["id"], ("PENDING",))
    if remittance is not None:
        remittance["status"] = "VOIDED"
        touch(remittance)
        speaker = db.speakers[remittance["speaker_id"]]
        speaker["pending_remittance_cents"] = \
            speaker["pending_remittance_cents"] - remittance["net_payable_cents"]
        touch(speaker)
    return ok(public(invoice))


# --- remittances ------------------------------------------------------------

@bp.get("/remittances")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def list_remittances():
    engagement_id = v.query_string("engagement_id")
    speaker_id = v.query_string("speaker_id")
    status = v.query_string("status")
    rows = []
    for row in db.remittances.values():
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/remittances/<remittance_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def read_remittance(remittance_id):
    return ok(public(get_remittance(remittance_id)))


@bp.post("/remittances/<remittance_id>/pay")
@roles("BureauAdmin")
def pay_remittance(remittance_id):
    remittance = get_remittance(remittance_id)
    data = v.body()
    v.opt_string(data, "payment_reference")

    if remittance["status"] != "APPROVED":
        fail(errors.ERR_REMITTANCE_NOT_APPROVED)

    speaker = db.speakers[remittance["speaker_id"]]
    if speaker["tax_form_status"] != "ON_FILE":
        fail(errors.ERR_SPEAKER_TAX_FORM_MISSING)

    remittance["status"] = "PAID"
    remittance["paid_at_utc"] = fmt_iso(db.now_utc())
    touch(remittance)

    speaker["pending_remittance_cents"] = \
        speaker["pending_remittance_cents"] - remittance["net_payable_cents"]
    touch(speaker)

    engagement = db.engagements[remittance["engagement_id"]]
    engagement["settlement_status"] = "REMITTED"
    touch(engagement)

    for expense in db.expenses.values():
        if expense["engagement_id"] == engagement["id"] and expense["status"] == "APPROVED":
            expense["status"] = "REIMBURSED"
            touch(expense)
    return ok(public(remittance))
