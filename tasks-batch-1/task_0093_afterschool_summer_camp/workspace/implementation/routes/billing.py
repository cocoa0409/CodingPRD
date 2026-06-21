"""Invoice, Payment, and AuditEntry routes (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NO_CONFIRMED_LINES,
    ERR_STALE_INVOICE_VERSION,
    ERR_OVERPAYMENT,
)
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    touch,
    audit,
    get_body,
    require_str,
    require_int,
    require_enum,
)
from services.calculations import (
    confirmed_lines,
    compute_line_tuition,
    compute_invoice_totals,
)
from services.lookups import get_invoice

bp = Blueprint("billing", __name__)


# ---------------------------------------------------------------------------
# Invoice reads
# ---------------------------------------------------------------------------
@bp.get("/invoices/<iid>")
def fetch_invoice(iid):
    require_roles(ROLE_GUARDIAN, ROLE_BILLING)
    rec = get_invoice(iid)
    return ok_object(serialize(rec), 200)


@bp.get("/invoices/<iid>/payments")
def list_invoice_payments(iid):
    require_roles(ROLE_GUARDIAN, ROLE_BILLING)
    get_invoice(iid)
    limit, offset = paginate_params(request.args)
    items = [p for p in db.payments.values() if p["invoice_id"] == iid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Invoice transitions
# ---------------------------------------------------------------------------
@bp.post("/invoices/<iid>/finalize")
def finalize_invoice(iid):
    caller = require_roles(ROLE_BILLING)
    invoice = get_invoice(iid)
    body = get_body()
    expected_version = require_int(body, "expected_invoice_version")

    # state precondition (priority 5)
    if invoice["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not DRAFT")
    # business: >= 1 CONFIRMED line
    lines = confirmed_lines(invoice["id"])
    if len(lines) < 1:
        raise APIError(ERR_NO_CONFIRMED_LINES, 409, "Invoice has no confirmed lines")
    # OCC
    if expected_version != invoice["version"]:
        raise APIError(ERR_STALE_INVOICE_VERSION, 412, "Stale invoice version")

    invoice["status"] = "FINALIZED"
    # freeze final tuition per line (final variant snapshots current discount)
    for e in lines:
        e["final_tuition_cents"] = compute_line_tuition(e)
        touch(e)
    # re-freeze totals over final lines (compute_invoice_totals reads final_tuition
    # because status is now FINALIZED)
    compute_invoice_totals(invoice)
    touch(invoice)
    audit("Invoice", invoice["id"], "INVOICE_FINALIZED", caller.role)
    return ok_object(serialize(invoice), 200)


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    caller = require_roles(ROLE_BILLING)
    invoice = get_invoice(iid)
    if invoice["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not DRAFT")
    invoice["status"] = "VOID"
    touch(invoice)
    audit("Invoice", invoice["id"], "INVOICE_VOIDED", caller.role)
    return ok_object(serialize(invoice), 200)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
@bp.post("/payments")
def create_payment():
    caller = require_roles(ROLE_BILLING)
    body = get_body()
    invoice_id = require_str(body, "invoice_id")
    amount_cents = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", {"CARD", "ACH", "WALLET"})
    invoice = get_invoice(invoice_id)

    # may pay only a FINALIZED invoice (state precondition)
    if invoice["status"] != "FINALIZED":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not FINALIZED")

    # overpayment guard
    outstanding = invoice["total_due_cents"] - invoice["amount_paid_cents"]
    if amount_cents > outstanding:
        raise APIError(ERR_OVERPAYMENT, 422, "Payment exceeds outstanding balance")

    payment = make_record(
        {
            "invoice_id": invoice_id,
            "amount_cents": amount_cents,
            "method": method,
        },
        versioned=False,
    )
    db.payments[payment["id"]] = payment

    invoice["amount_paid_cents"] += amount_cents
    touch(invoice)
    if invoice["amount_paid_cents"] >= invoice["total_due_cents"]:
        invoice["status"] = "PAID"
        touch(invoice)
        audit("Invoice", invoice["id"], "INVOICE_PAID", caller.role)

    return ok_object(serialize(payment), 201)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@bp.get("/audit-entries")
def list_audit_entries():
    require_roles(ROLE_DIRECTOR, ROLE_BILLING)
    limit, offset = paginate_params(request.args)
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    items = list(db.audit_entries.values())
    if entity_type is not None:
        items = [a for a in items if a["entity_type"] == entity_type]
    if entity_id is not None:
        items = [a for a in items if a["entity_id"] == entity_id]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
