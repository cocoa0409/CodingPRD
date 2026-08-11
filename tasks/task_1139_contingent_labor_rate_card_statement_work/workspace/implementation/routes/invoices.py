from decimal import Decimal

from flask import Blueprint, request

from db import stamp_new, store, touch
from envelope import ok, ok_list
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_INVOICE_ALREADY_OPEN,
    ERR_INVOICE_EMPTY,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    raise_err,
)
from security import NO_WORKER_READ, require_roles
from services import (
    FEE_RATE_AT_OR_ABOVE,
    FEE_RATE_BELOW,
    FEE_TIER_THRESHOLD_CENTS,
    LINE_INVOICE_FEE_CENTS,
    get_open_invoice,
    get_or_create_open_invoice,
    invoice_lines_of,
    recompute_invoice,
    round_cents,
)
from validators import apply_filters, get_body, paginate, req_date, req_str
import serializers

bp = Blueprint("invoices", __name__)


def _get_invoice(invoice_id):
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_NOT_FOUND, f"Invoice {invoice_id} not found.")
    return inv


@bp.post("/v1/invoices")
def create_invoice():
    require_roles("FinanceAnalyst")
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if supplier_id not in store.suppliers:
        raise_err(ERR_NOT_FOUND, f"Supplier {supplier_id} not found.")
    if get_open_invoice(supplier_id) is not None:
        raise_err(ERR_INVOICE_ALREADY_OPEN, "The supplier already has an OPEN invoice.")
    rec = {
        "supplier_id": supplier_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "line_count": 0,
        "subtotal_cents": 0,
        "processing_fee_cents": 0,
        "total_cents": 0,
        "consolidation_savings_cents": 0,
        "finalized_by_user_id": None,
        "paid_by_user_id": None,
        "void_reason": None,
    }
    stamp_new(rec)
    store.invoices[rec["id"]] = rec
    return ok(serializers.invoice(rec), 201)


@bp.get("/v1/invoices")
def list_invoices():
    require_roles(*NO_WORKER_READ)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.invoices.values()), filters)
    page, total, limit, offset = paginate(records, serializers.invoice)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/invoices/<invoice_id>")
def get_invoice(invoice_id):
    require_roles(*NO_WORKER_READ)
    return ok(serializers.invoice(_get_invoice(invoice_id)))


@bp.post("/v1/invoices/<invoice_id>/finalize")
def finalize_invoice(invoice_id):
    uid, _ = require_roles("FinanceAnalyst")
    inv = _get_invoice(invoice_id)
    if inv["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN invoice can be finalized.")
    recompute_invoice(inv)
    if inv["line_count"] < 1:
        raise_err(ERR_INVOICE_EMPTY, "An invoice with zero lines cannot be finalized.")
    subtotal = inv["subtotal_cents"]
    # tier is keyed on the PRE-fee subtotal, never on the post-fee total
    rate = FEE_RATE_BELOW if subtotal < FEE_TIER_THRESHOLD_CENTS else FEE_RATE_AT_OR_ABOVE
    inv["processing_fee_cents"] = round_cents(Decimal(subtotal) * rate)
    inv["total_cents"] = subtotal + inv["processing_fee_cents"]
    inv["consolidation_savings_cents"] = (
        (inv["line_count"] - 1) * LINE_INVOICE_FEE_CENTS if inv["line_count"] >= 1 else 0
    )
    inv["finalized_by_user_id"] = uid
    inv["status"] = "FINALIZED"
    touch(inv)
    for line in invoice_lines_of(inv["id"]):
        if line["milestone_id"]:
            m = store.milestones.get(line["milestone_id"])
            if m is not None and m["payment_status"] == "UNINVOICED":
                m["payment_status"] = "INVOICED"
                touch(m)
    return ok(serializers.invoice(inv))


@bp.post("/v1/invoices/<invoice_id>/mark-paid")
def mark_paid_invoice(invoice_id):
    uid, _ = require_roles("FinanceAnalyst")
    inv = _get_invoice(invoice_id)
    if inv["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Only a FINALIZED invoice can be marked paid.")
    if uid == inv["finalized_by_user_id"]:
        raise_err(
            ERR_SOD_VIOLATION,
            "The caller who finalized the invoice cannot also mark it paid.",
        )
    inv["paid_by_user_id"] = uid
    inv["status"] = "PAID"
    touch(inv)
    for line in invoice_lines_of(inv["id"]):
        if line["milestone_id"]:
            m = store.milestones.get(line["milestone_id"])
            if m is not None and m["payment_status"] == "INVOICED":
                m["payment_status"] = "PAID"
                touch(m)
    return ok(serializers.invoice(inv))


@bp.post("/v1/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    require_roles("FinanceAnalyst")
    body = get_body()
    reason = req_str(body, "reason")
    inv = _get_invoice(invoice_id)
    if inv["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Only a FINALIZED invoice can be voided.")
    inv["void_reason"] = reason
    inv["status"] = "VOIDED"
    lines = invoice_lines_of(inv["id"])
    fresh = get_or_create_open_invoice(inv["supplier_id"])
    for line in lines:
        line["invoice_id"] = fresh["id"]
        if line["milestone_id"]:
            m = store.milestones.get(line["milestone_id"])
            if m is not None and m["payment_status"] == "INVOICED":
                m["payment_status"] = "UNINVOICED"
                touch(m)
    inv["line_count"] = 0
    inv["subtotal_cents"] = 0
    touch(inv)
    recompute_invoice(fresh)
    touch(fresh)
    return ok(serializers.invoice(inv))


# ---- invoice lines -------------------------------------------------
@bp.get("/v1/invoice-lines")
def list_invoice_lines():
    require_roles(*NO_WORKER_READ)
    filters = {
        "invoice_id": request.args.get("invoice_id"),
        "timesheet_id": request.args.get("timesheet_id"),
        "milestone_id": request.args.get("milestone_id"),
    }
    records = apply_filters(list(store.invoice_lines.values()), filters)
    page, total, limit, offset = paginate(records, serializers.invoice_line)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/invoice-lines/<line_id>")
def get_invoice_line(line_id):
    require_roles(*NO_WORKER_READ)
    line = store.invoice_lines.get(line_id)
    if line is None:
        raise_err(ERR_NOT_FOUND, f"Invoice line {line_id} not found.")
    return ok(serializers.invoice_line(line))
