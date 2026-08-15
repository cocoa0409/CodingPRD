"""Invoices (PRD 3.6): payments, SoD-gated waivers, refunds."""

import db
import serializers
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from validate import get_invoice_masked, req_int, req_str

READ_ROLES = ["FinanceAdmin", "Scheduler", "OrgRequester"]


@endpoint("GET", "/campus/invoices/{id}", roles=READ_ROLES, code=200)
def get_invoice_detail(ctx):
    return one(serializers.invoice(get_invoice_masked(ctx, ctx.id)))


@endpoint("GET", "/campus/invoices", roles=READ_ROLES, code=200)
def list_invoices(ctx):
    rows = db.all_of(db.invoices)
    if ctx.is_org_requester:
        rows = [r for r in rows if r.get("org_id") == ctx.user_id]
    return list_response(
        rows,
        ctx.args,
        serializers.invoice,
        mapping={
            "event_id": lambda r: r.get("event_id"),
            "org_id": lambda r: r.get("org_id"),
            "status": lambda r: r.get("status"),
        },
    )


def _remaining(invoice):
    return (
        invoice.get("total_cents", 0)
        - invoice.get("paid_cents", 0)
        - invoice.get("waived_cents", 0)
    )


def _apply_settlement(invoice):
    """paid + waived reaching total exactly moves the invoice to PAID, whether
    it started PROVISIONAL, FINALIZED, or PARTIALLY_PAID; a partial payment
    moves FINALIZED to PARTIALLY_PAID."""
    if invoice.get("paid_cents", 0) + invoice.get("waived_cents", 0) == invoice.get("total_cents", 0):
        invoice["status"] = "PAID"
    elif invoice["status"] == "FINALIZED":
        invoice["status"] = "PARTIALLY_PAID"


@endpoint("POST", "/campus/invoices/{id}/pay", roles=["OrgRequester", "FinanceAdmin"], code=200)
def pay_invoice(ctx):
    invoice = get_invoice_masked(ctx, ctx.id)  # OrgRequester ownership masked as 404
    amount = req_int(ctx.body, "amount_cents")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be positive.")
    # Prepayment of a PROVISIONAL invoice is allowed; FINALIZED and
    # PARTIALLY_PAID accept payments ordinarily.  Payments on VOIDED or
    # REFUNDED invoices - and any amount beyond the remaining balance - are
    # overpayments.  (A PAID invoice has remaining balance zero.)
    if invoice["status"] in ("VOIDED", "REFUNDED"):
        raise ApiError("ERR_OVERPAYMENT", "A voided or refunded invoice accepts no payments.")
    if amount > _remaining(invoice):
        raise ApiError("ERR_OVERPAYMENT", "The payment exceeds the remaining balance.")
    invoice["paid_cents"] = invoice.get("paid_cents", 0) + amount
    _apply_settlement(invoice)
    db.touch(invoice)
    return one(serializers.invoice(invoice))


@endpoint("POST", "/campus/invoices/{id}/waive", roles=["FinanceAdmin"], code=200)
def waive_invoice(ctx):
    invoice = get_invoice_masked(ctx, ctx.id)
    amount = req_int(ctx.body, "amount_cents")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be positive.")
    reason = req_str(ctx.body, "reason")
    if invoice["status"] in ("VOIDED", "REFUNDED"):
        raise ApiError("ERR_INVALID_STATE", "A voided or refunded invoice accepts no waivers.")
    # Segregation of duties: the waiving operator must differ from the event's
    # recorded approver.
    event = db.event_reservations.get(invoice.get("event_id"))
    if event is not None and event.get("approved_by_user_id") is not None and (
        event.get("approved_by_user_id") == ctx.user_id
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The waiving operator must differ from the event's approver.",
        )
    if amount > _remaining(invoice):
        raise ApiError("ERR_OVERPAYMENT", "The waiver exceeds the remaining balance.")
    invoice["waived_cents"] = invoice.get("waived_cents", 0) + amount
    _apply_settlement(invoice)
    db.touch(invoice)
    return one(serializers.invoice(invoice))


@endpoint("POST", "/campus/invoices/{id}/refund", roles=["FinanceAdmin"], code=200)
def refund_invoice(ctx):
    invoice = get_invoice_masked(ctx, ctx.id)
    amount = req_int(ctx.body, "amount_cents")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be positive.")
    # Refunds run against money actually collected, from PAID or
    # PARTIALLY_PAID invoices only.
    if invoice["status"] not in ("PAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE", "Only a paid invoice can be refunded.")
    if amount > invoice.get("paid_cents", 0) - invoice.get("refunded_cents", 0):
        raise ApiError("ERR_REFUND_EXCEEDS_PAID", "The refund exceeds what was actually paid.")
    invoice["refunded_cents"] = invoice.get("refunded_cents", 0) + amount
    if invoice["refunded_cents"] == invoice.get("paid_cents", 0):
        invoice["status"] = "REFUNDED"
    db.touch(invoice)
    return one(serializers.invoice(invoice))
