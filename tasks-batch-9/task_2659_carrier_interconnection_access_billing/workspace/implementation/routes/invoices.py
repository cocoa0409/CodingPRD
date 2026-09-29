"""Access invoice issuance, payment and write-off (PRD 3.8)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE,
                  DISPUTE_RESOLUTION_OFFICER, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate, carrier_of_invoice,
                  scope_check, scope_filter, segregation_check)
from constants import DISPUTE_FILING_WINDOW_DAYS, RATE_ELEMENT_BY_JURISDICTION
from dec import q2
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_invoice, get_usage_batch, invoice_for_batch
from services import reserve
from services.invoicing import derive_lifecycle, recompute_open_balance
from store import base_record, db, now, ordered, touch

bp = Blueprint("invoices", __name__)

ZERO2 = Decimal("0.00")


def _rate_authority_filing_id(batch):
    """The EFFECTIVE filing that governed the largest jurisdiction subtotal at
    rating, ranked by subtotal descending, ties broken by rate_element ascending."""
    filings = batch.get("_rate_filing_ids") or {}
    ranked = []
    for jurisdiction, field in (("INTERSTATE", "interstate_amount_usd"),
                                ("INTRASTATE", "intrastate_amount_usd"),
                                ("LOCAL", "local_amount_usd")):
        ranked.append((-batch[field], RATE_ELEMENT_BY_JURISDICTION[jurisdiction],
                       filings.get(jurisdiction)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]


@bp.post("/access-invoices")
def create_invoice():
    authenticate((ACCESS_BILLING_ANALYST,))
    payload = v.body()
    batch_id = v.string(payload, "usage_batch_id")
    due_date = v.timestamp(payload, "due_date")

    batch = get_usage_batch(batch_id)

    if batch["status"] != "RATED":
        raise ApiError("ERR_INVALID_BATCH_STATE",
                       "only a RATED batch may be invoiced")
    if invoice_for_batch(batch["id"]) is not None:
        raise ApiError("ERR_BATCH_ALREADY_INVOICED",
                       "this batch already carries an invoice")

    invoice = base_record()
    invoice.update({
        "carrier_id": batch["carrier_id"],
        "usage_batch_id": batch["id"],
        "rate_authority_filing_id": _rate_authority_filing_id(batch),
        "lifecycle_status": "DRAFT",
        "payment_status": "UNPAID",
        "dispute_status": "NONE",
        "billed_amount_usd": q2(batch["rated_amount_usd"]),
        "credited_amount_usd": ZERO2,
        "paid_amount_usd": ZERO2,
        "open_balance_usd": ZERO2,
        "disputed_amount_usd": ZERO2,
        "due_date": due_date,
        "issued_at": None,
        "dispute_deadline_at": None,
        "issued_by_user_id": None,
        "interstate_amount_usd": batch["interstate_amount_usd"],
        "intrastate_amount_usd": batch["intrastate_amount_usd"],
        "local_amount_usd": batch["local_amount_usd"],
        "rating_variant": batch["rating_variant"],
        "adjustment_count": 0,
        "written_off_at": None,
    })
    recompute_open_balance(invoice)
    db.invoices[invoice["id"]] = invoice

    batch["status"] = "INVOICED"
    touch(batch)
    return object_response(invoice, 201)


@bp.get("/access-invoices/<invoice_id>")
def read_invoice(invoice_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, DISPUTE_RESOLUTION_OFFICER,
                          CARRIER_REPRESENTATIVE))
    invoice = get_invoice(invoice_id)
    scope_check(actor, invoice["carrier_id"])
    return object_response(invoice)


@bp.get("/access-invoices")
def list_invoices():
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, DISPUTE_RESOLUTION_OFFICER,
                          CARRIER_REPRESENTATIVE))
    rows = ordered(db.invoices)
    for param, field in (("carrier_id", "carrier_id"),
                         ("usage_batch_id", "usage_batch_id"),
                         ("rate_authority_filing_id", "rate_authority_filing_id"),
                         ("lifecycle_status", "lifecycle_status"),
                         ("payment_status", "payment_status"),
                         ("dispute_status", "dispute_status")):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[field] == value]
    rows = scope_filter(actor, rows, carrier_of_invoice)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/access-invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    actor = authenticate((ACCESS_BILLING_ANALYST,))
    invoice = get_invoice(invoice_id)

    if invoice["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_INVOICE_STATE", "only a DRAFT invoice may be issued")
    if invoice["billed_amount_usd"] <= ZERO2:
        raise ApiError("ERR_EMPTY_INVOICE", "an invoice with no billed amount cannot be issued")

    invoice["lifecycle_status"] = "ISSUED"
    invoice["issued_at"] = now()
    invoice["dispute_deadline_at"] = now() + timedelta(days=DISPUTE_FILING_WINDOW_DAYS)
    invoice["issued_by_user_id"] = actor.user_id
    recompute_open_balance(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "INVOICE_CREATED", invoice["id"])
    return object_response(invoice)


@bp.post("/access-invoices/<invoice_id>/payments")
def apply_payment(invoice_id):
    actor = authenticate((CARRIER_REPRESENTATIVE, ACCESS_BILLING_ANALYST))
    invoice = get_invoice(invoice_id)
    payload = v.body()
    amount = v.number(payload, "amount_usd", 2)
    remittance_reference = v.string(payload, "remittance_reference")

    scope_check(actor, invoice["carrier_id"])

    if (invoice["lifecycle_status"] != "ISSUED"
            or invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID")):
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "payments only apply to an ISSUED invoice that is not yet settled")
    if amount > invoice["open_balance_usd"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "amount_usd exceeds the invoice open balance")

    invoice["paid_amount_usd"] = q2(invoice["paid_amount_usd"] + amount)
    invoice["_last_remittance_reference"] = remittance_reference
    recompute_open_balance(invoice)
    invoice["payment_status"] = "PAID" if invoice["open_balance_usd"] <= ZERO2 \
        else "PARTIALLY_PAID"
    derive_lifecycle(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "INVOICE_PAYMENT_APPLIED", invoice["id"])
    return object_response(invoice)


@bp.post("/access-invoices/<invoice_id>/write-off")
def write_off_invoice(invoice_id):
    actor = authenticate((REVENUE_ASSURANCE_CONTROLLER,))
    invoice = get_invoice(invoice_id)
    payload = v.body()
    reason = v.string(payload, "write_off_reason")

    segregation_check(actor, invoice["issued_by_user_id"])

    if invoice["payment_status"] == "WRITTEN_OFF":
        raise ApiError("ERR_INVOICE_ALREADY_WRITTEN_OFF",
                       "this invoice has already been written off")
    if invoice["lifecycle_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "only an ISSUED invoice may be written off")
    if invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "a settled invoice may not be written off")
    if invoice["dispute_status"] == "DISPUTED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "an invoice with an open dispute may not be written off")
    if now() < invoice["due_date"]:
        raise ApiError("ERR_INVOICE_NOT_YET_DUE",
                       "the invoice is not yet due")

    written_off_balance = invoice["open_balance_usd"]
    invoice["payment_status"] = "WRITTEN_OFF"
    invoice["written_off_at"] = now()
    invoice["_write_off_reason"] = reason
    derive_lifecycle(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    reserve.recompute(carrier, "INVOICE_WRITTEN_OFF", invoice["id"],
                      write_off_amount_usd=written_off_balance)
    return object_response(invoice)
