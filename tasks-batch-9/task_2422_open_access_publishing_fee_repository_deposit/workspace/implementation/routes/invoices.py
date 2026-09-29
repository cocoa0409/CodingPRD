"""Publisher invoices: pricing, validation, payment approval and payment."""
from flask import Blueprint, g

import constants as C
import schemas
from auth import endpoint
from db import db, new_row, set_fields
from errors import ApiError
from response import object_response
from routes.helpers import paged
from services import funding
from services.determination import effective_determination
from services.invoicing import price_invoice
from validation import (
    filter_enum,
    get_body,
    invalid,
    req_date,
    req_enum,
    req_fraction,
    req_int,
    req_str,
    resolve,
    resolve_body_fk,
    resolve_filter,
)

bp = Blueprint("invoices", __name__)

FUNDED_STATUSES = ("FUNDED", "PARTIALLY_FUNDED", "SELF_FUNDED")


@bp.post("/publisher-invoices")
@endpoint(["ScholCommLibrarian"])
def create_invoice():
    body = get_body()
    publisher = resolve_body_fk(body, "publisher_id", "publisher")
    article = resolve_body_fk(body, "article_id", "article")
    if publisher is None:
        invalid("publisher_id is required")
    if article is None:
        invalid("article_id is required")
    invoice_number = req_str(body, "invoice_number")
    invoice_amount_cents = req_int(body, "invoice_amount_cents", minimum=0)
    currency = req_enum(body, "currency", ("USD",))
    claimed_discount_pct = req_fraction(body, "claimed_discount_pct", 0, "0.95")
    vat_pct = req_fraction(body, "vat_pct", 0, "0.30")
    invoice_date_raw, _ = req_date(body, "invoice_date")

    if effective_determination(article["id"]) is None:
        raise ApiError("ERR_ELIGIBILITY_NOT_DETERMINED", 409)

    for other in db.invoices.values():
        if other["publisher_id"] == publisher["id"] and other["invoice_number"] == invoice_number:
            raise ApiError("ERR_DUPLICATE_INVOICE_NUMBER", 409)

    row = new_row(
        publisher_id=publisher["id"],
        article_id=article["id"],
        invoice_number=invoice_number,
        invoice_amount_cents=invoice_amount_cents,
        currency=currency,
        claimed_discount_pct=claimed_discount_pct,
        vat_pct=vat_pct,
        invoice_date=invoice_date_raw,
        entitled_discount_pct=0,
        net_cents=0,
        vat_cents=0,
        expected_amount_cents=0,
        variance_cents=0,
        validation_outcome=None,
        status="RECEIVED",
        dispute_reason=None,
        payment_approved_by_user_id=None,
        payment_reference=None,
    )
    db.invoices[row["id"]] = row
    row.update(price_invoice(row))
    return object_response(schemas.serialize(row, schemas.INVOICE), 201)


@bp.get("/publisher-invoices")
@endpoint(["ScholCommLibrarian", "FundManager"])
def list_invoices():
    publisher_id = resolve_filter("publisher", "publisher_id")
    article_id = resolve_filter("article", "article_id")
    status = filter_enum("status", C.INVOICE_STATUSES)
    rows = list(db.invoices.values())
    if publisher_id:
        rows = [i for i in rows if i["publisher_id"] == publisher_id]
    if article_id:
        rows = [i for i in rows if i["article_id"] == article_id]
    if status:
        rows = [i for i in rows if i["status"] == status]
    return paged(rows, schemas.INVOICE)


@bp.get("/publisher-invoices/<invoice_id>")
@endpoint(["ScholCommLibrarian", "FundManager"])
def get_invoice(invoice_id):
    row = resolve("invoice", invoice_id)
    return object_response(schemas.serialize(row, schemas.INVOICE))


@bp.post("/publisher-invoices/<invoice_id>/validation")
@endpoint(["ScholCommLibrarian"])
def validate_invoice(invoice_id):
    invoice = resolve("invoice", invoice_id)
    if invoice["status"] != "RECEIVED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", 409)
    pricing = price_invoice(invoice)
    outcome = pricing["validation_outcome"]
    changes = dict(pricing)
    if outcome in ("MATCH", "WITHIN_TOLERANCE"):
        changes["status"] = "VALIDATED"
    else:
        changes["status"] = "DISPUTED"
        changes["dispute_reason"] = outcome
    set_fields(invoice, _force=True, **changes)
    return object_response(schemas.serialize(invoice, schemas.INVOICE))


@bp.post("/publisher-invoices/<invoice_id>/payment-approval")
@endpoint(["FundManager"])
def approve_payment(invoice_id):
    invoice = resolve("invoice", invoice_id)
    if invoice["status"] != "VALIDATED":
        raise ApiError("ERR_INVOICE_INVALID_STATE", 409)
    article = db.articles[invoice["article_id"]]
    if article["funding_status"] not in FUNDED_STATUSES:
        raise ApiError("ERR_ARTICLE_NOT_FUNDED", 409)
    set_fields(
        invoice,
        _force=True,
        status="APPROVED_FOR_PAYMENT",
        payment_approved_by_user_id=g.user_id,
    )
    return object_response(schemas.serialize(invoice, schemas.INVOICE))


@bp.post("/publisher-invoices/<invoice_id>/payment")
@endpoint(["FundManager"])
def pay_invoice(invoice_id):
    invoice = resolve("invoice", invoice_id)
    body = get_body()
    payment_reference = req_str(body, "payment_reference")
    if invoice["status"] != "APPROVED_FOR_PAYMENT":
        raise ApiError("ERR_INVOICE_INVALID_STATE", 409)
    if g.user_id == invoice["payment_approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)

    set_fields(invoice, _force=True, status="PAID", payment_reference=payment_reference)

    article = db.articles[invoice["article_id"]]
    request_row = funding.approved_request_of_article(article["id"])
    if request_row is not None:
        set_fields(request_row, _force=True, status="PAID")
        funding.disburse_allocations(request_row)
        funding.recompute_author_totals(article["corresponding_author_id"])
    return object_response(schemas.serialize(invoice, schemas.INVOICE))
