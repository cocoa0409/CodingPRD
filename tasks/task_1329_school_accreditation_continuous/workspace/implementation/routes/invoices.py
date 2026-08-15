"""Invoice and Payment endpoints."""
from flask import Blueprint, request

from db import DB, clock_now, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404, issue_invoice
from util import (
    as_enum,
    as_int,
    body,
    paginate,
    pagination,
    parse_dt,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("invoices", __name__)

INVOICE_TYPES = {"ANNUAL_FEE", "VISIT_FEE", "RENEWAL_FEE"}


def invoice_view(inv):
    return {k: v for k, v in inv.items() if not k.startswith("_")}


def payment_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _payments_for(invoice_id):
    return [p for p in DB["payments"].values() if p["invoice_id"] == invoice_id]


def _paid_total(invoice_id):
    return sum(p["amount_cents"] for p in _payments_for(invoice_id))


@bp.post("/accreditation/systems/<id>/invoices")
def create_invoice(id):
    auth(["SystemBursar"])
    system = get_or_404("systems", id, "InstitutionSystem")
    data = body()
    billing_year = as_int(required(data, "billing_year"), "billing_year")
    invoice_type = as_enum(required(data, "invoice_type"), "invoice_type", INVOICE_TYPES)
    invoice = issue_invoice(system, invoice_type, billing_year)
    return ok(invoice_view(invoice), status=201)


@bp.get("/accreditation/systems/<id>/invoices")
def list_system_invoices(id):
    auth(["AccreditationOfficer", "SystemBursar"])
    get_or_404("systems", id, "InstitutionSystem")
    limit, offset = pagination()
    rows = [i for i in DB["invoices"].values() if i["system_id"] == id]
    rows.sort(key=lambda i: i["created_at"])
    status = request.args.get("status")
    invoice_type = request.args.get("invoice_type")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if invoice_type:
        rows = [r for r in rows if r["invoice_type"] == invoice_type]
    page, total = paginate(rows, limit, offset)
    return ok_list([invoice_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/invoices/<id>")
def get_invoice(id):
    auth(["AccreditationOfficer", "SystemBursar"])
    row = get_or_404("invoices", id, "Invoice")
    return ok(invoice_view(row))


@bp.post("/accreditation/invoices/<id>/payments")
def post_payment(id):
    auth(["SystemBursar"])
    invoice = get_or_404("invoices", id, "Invoice")
    data = body()
    amount_cents = as_int(required(data, "amount_cents"), "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_VALIDATION", 400, "amount_cents must be > 0")
    paid_at_raw = required(data, "paid_at")
    parse_dt(paid_at_raw, "paid_at")  # validate format only
    expected_invoice_version = required(data, "expected_invoice_version")
    if not isinstance(expected_invoice_version, int) or isinstance(
        expected_invoice_version, bool
    ):
        raise ApiError(
            "ERR_VALIDATION", 400, "expected_invoice_version must be an integer"
        )

    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Invoice is not open for payments",
        )
    if invoice["version"] != expected_invoice_version:
        raise ApiError(
            "ERR_STALE_INVOICE_VERSION",
            412,
            "expected_invoice_version does not match the invoice's current version",
        )
    paid_so_far = _paid_total(id)
    outstanding = invoice["amount_cents"] - paid_so_far
    if amount_cents > outstanding:
        raise ApiError(
            "ERR_FISCAL_VIOLATION",
            422,
            "Payment exceeds the invoice's outstanding balance",
        )
    record = {
        "id": new_id(),
        "invoice_id": id,
        "amount_cents": amount_cents,
        "paid_at": paid_at_raw,
    }
    # Payment carries id and created_at only (PRD 2.4).
    stamp_new(record, with_version=False)
    DB["payments"][record["id"]] = record
    new_paid = paid_so_far + amount_cents
    if new_paid == invoice["amount_cents"]:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)
    return ok(payment_view(record), status=201)


@bp.get("/accreditation/invoices/<id>/payments")
def list_payments(id):
    auth(["AccreditationOfficer", "SystemBursar"])
    get_or_404("invoices", id, "Invoice")
    limit, offset = pagination()
    rows = _payments_for(id)
    rows.sort(key=lambda p: p["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([payment_view(r) for r in page], total, limit, offset)


@bp.post("/accreditation/invoices/<id>/void")
def void_invoice(id):
    auth(["SystemBursar"])
    invoice = get_or_404("invoices", id, "Invoice")
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only ISSUED invoices may be voided")
    if _payments_for(id):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Invoice has payments and cannot be voided",
        )
    invoice["status"] = "VOID"
    touch(invoice)
    return ok(invoice_view(invoice))
