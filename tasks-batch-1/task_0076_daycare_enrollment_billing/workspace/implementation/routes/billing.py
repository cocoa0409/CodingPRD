"""Invoice, Payment, and TaxStatement endpoints."""
from __future__ import annotations

import re
from flask import Blueprint, g, request

from db import db, clock, now_iso
from middleware import require_roles, current_user_id
from response import ok_object, ok_array
from common import (
    base_entity, touch, public, get_or_404, get_body,
    require_str, require_int, require_enum, parse_pagination, paginate,
)
from errors import (
    APIError, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE, ERR_EMPTY_INVOICE, ERR_OVERPAYMENT,
    ERR_INVOICE_HAS_PAYMENTS, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)

bp = Blueprint("billing", __name__)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
PAYMENT_METHODS = {"CARD", "ACH", "CASH"}


def _family_active_enrollments(family_id):
    out = []
    for e in db.enrollments.values():
        if e["status"] != "ACTIVE":
            continue
        c = db.children.get(e["child_id"])
        if c is not None and c["family_id"] == family_id:
            out.append(e)
    return out


def _family_late_fines_in_month(family_id, billing_month):
    total = 0
    for a in db.attendance_records.values():
        if a["status"] != "CHECKED_OUT":
            continue
        if not a["service_date"].startswith(billing_month + "-"):
            continue
        e = db.enrollments.get(a["enrollment_id"])
        if e is None:
            continue
        c = db.children.get(e["child_id"])
        if c is not None and c["family_id"] == family_id:
            total += a["late_fine_cents"]
    return total


# ----- Invoices -----
@bp.post("/families/<fid>/invoices")
@require_roles("BillingAdmin")
def create_invoice(fid):
    get_or_404(db.families, fid, "family")
    body = get_body()
    billing_month = require_str(body, "billing_month")
    if not _MONTH_RE.match(billing_month):
        raise APIError(ERR_INVALID_REQUEST, 400, "billing_month must be YYYY-MM")
    ent = base_entity()
    ent.update({
        "family_id": fid,
        "billing_month": billing_month,
        "status": "DRAFT",
        "tuition_cents": 0,
        "late_fines_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "issued_at": None,
    })
    db.invoices[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/families/<fid>/invoices")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_invoices(fid):
    get_or_404(db.families, fid, "family")
    if g.user_role == "Parent" and current_user_id() != fid:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this family")
    limit, offset = parse_pagination()
    rows = [i for i in db.invoices.values() if i["family_id"] == fid]
    rows.sort(key=lambda i: i["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(i) for i in page], limit, offset, total, 200)


@bp.get("/invoices/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def get_invoice(rid):
    ent = get_or_404(db.invoices, rid, "invoice")
    if g.user_role == "Parent" and current_user_id() != ent["family_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this invoice")
    return ok_object(public(ent), 200)


@bp.post("/invoices/<rid>/issue")
@require_roles("BillingAdmin")
def issue_invoice(rid):
    ent = get_or_404(db.invoices, rid, "invoice")
    if ent["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not DRAFT")
    family_id = ent["family_id"]
    active = _family_active_enrollments(family_id)
    late = _family_late_fines_in_month(family_id, ent["billing_month"])
    if not active and late == 0:
        raise APIError(ERR_EMPTY_INVOICE, 409, "No active enrollments and no late fines")
    tuition = sum(e["monthly_net_tuition_cents"] for e in active)
    ent["tuition_cents"] = tuition
    ent["late_fines_cents"] = late
    ent["total_cents"] = tuition + late
    ent["issued_at"] = now_iso()
    ent["status"] = "ISSUED"
    touch(ent)
    family = db.families.get(family_id)
    family["account_balance_cents"] += ent["total_cents"]
    touch(family)
    return ok_object(public(ent), 200)


@bp.post("/invoices/<rid>/void")
@require_roles("BillingAdmin")
def void_invoice(rid):
    ent = get_or_404(db.invoices, rid, "invoice")
    if ent["status"] not in ("DRAFT", "ISSUED"):
        raise APIError(ERR_INVALID_STATE, 409, "Invoice cannot be voided from its current state")
    if ent["status"] == "ISSUED":
        if ent["amount_paid_cents"] > 0:
            raise APIError(ERR_INVOICE_HAS_PAYMENTS, 409, "Invoice has payments")
        family = db.families.get(ent["family_id"])
        family["account_balance_cents"] -= ent["total_cents"]
        touch(family)
    ent["status"] = "VOID"
    touch(ent)
    return ok_object(public(ent), 200)


# ----- Payments -----
@bp.post("/payments")
@require_roles("BillingAdmin", "Parent")
def create_payment():
    body = get_body()
    invoice_id = require_str(body, "invoice_id")
    amount = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", PAYMENT_METHODS)
    expected_version = require_int(body, "expected_invoice_version")
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "invoice_id does not exist")
    if g.user_role == "Parent" and current_user_id() != invoice["family_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this invoice")
    # state: must be ISSUED to accept payment
    if invoice["status"] != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not ISSUED")
    # OCC (priority 18)
    if expected_version != invoice["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "Invoice version mismatch")
    # overpayment guard (priority 16)
    outstanding = invoice["total_cents"] - invoice["amount_paid_cents"]
    if amount > outstanding:
        raise APIError(ERR_OVERPAYMENT, 422, "Payment exceeds outstanding balance")

    pay = base_entity(versioned=False)
    pay.update({
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "method": method,
    })
    db.payments[pay["id"]] = pay

    invoice["amount_paid_cents"] += amount
    touch(invoice)
    if invoice["amount_paid_cents"] >= invoice["total_cents"]:
        invoice["status"] = "PAID"
        family = db.families.get(invoice["family_id"])
        family["account_balance_cents"] -= invoice["total_cents"]
        touch(family)
    return ok_object(public(pay), 201)


@bp.get("/invoices/<rid>/payments")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_payments(rid):
    invoice = get_or_404(db.invoices, rid, "invoice")
    if g.user_role == "Parent" and current_user_id() != invoice["family_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this invoice")
    limit, offset = parse_pagination()
    rows = [p for p in db.payments.values() if p["invoice_id"] == rid]
    rows.sort(key=lambda p: p["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(p) for p in page], limit, offset, total, 200)


# ----- Tax statements -----
@bp.post("/families/<fid>/tax-statements")
@require_roles("BillingAdmin", "Parent")
def create_tax_statement(fid):
    family = get_or_404(db.families, fid, "family")
    if g.user_role == "Parent" and current_user_id() != fid:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this family")
    body = get_body()
    tax_year = require_int(body, "tax_year", minimum=2000)

    total_paid = 0
    for p in db.payments.values():
        inv = db.invoices.get(p["invoice_id"])
        if inv is None or inv["family_id"] != fid:
            continue
        if inv["status"] != "PAID":
            continue
        if int(inv["billing_month"].split("-")[0]) != tax_year:
            continue
        total_paid += p["amount_cents"]

    child_ids = set()
    for e in db.enrollments.values():
        if e["status"] != "ACTIVE":
            continue
        c = db.children.get(e["child_id"])
        if c is None or c["family_id"] != fid:
            continue
        if int(e["created_at"][:4]) <= tax_year:
            child_ids.add(c["id"])

    ent = base_entity(versioned=False)
    ent.update({
        "family_id": fid,
        "tax_year": tax_year,
        "total_paid_cents": total_paid,
        "child_count": len(child_ids),
    })
    db.tax_statements[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/families/<fid>/tax-statements")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_tax_statements(fid):
    get_or_404(db.families, fid, "family")
    if g.user_role == "Parent" and current_user_id() != fid:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this family")
    limit, offset = parse_pagination()
    tax_year = request.args.get("tax_year")
    rows = [t for t in db.tax_statements.values() if t["family_id"] == fid]
    if tax_year is not None:
        try:
            ty = int(tax_year)
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "tax_year must be an integer")
        rows = [t for t in rows if t["tax_year"] == ty]
    rows.sort(key=lambda t: t["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(t) for t in page], limit, offset, total, 200)
