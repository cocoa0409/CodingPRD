"""Invoice endpoints (PRD §3.9)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from db import db, parse_iso, stamp_create, stamp_update, serialize
from errors import err
from middleware import enforce_role, require_roles
from response import success_object
from services.calculations import three_way_match
from services.lookups import find_invoice, find_purchase_order
from validate import (
    get_json_body,
    require_fields,
    require_int,
    require_number,
    require_string,
)

bp = Blueprint("invoices", __name__)


@bp.post("/invoices")
@require_roles("Supplier")
def submit_invoice():
    body = get_json_body()
    require_fields(body, [
        "purchase_order_id", "supplier_id", "invoice_no", "invoice_date",
        "invoiced_quantity", "invoiced_amount_cents",
        "tax_amount_cents", "tax_rate_declared",
    ])
    po_id = require_string(body["purchase_order_id"], "purchase_order_id")
    po = db.purchase_orders.get(po_id)
    if po is None:
        raise err("ERR_VALIDATION", "purchase_order_id does not exist.")
    supplier_id = require_string(body["supplier_id"], "supplier_id")
    if supplier_id != po.get("supplier_id"):
        raise err("ERR_VALIDATION", "supplier_id does not match PO.supplier_id.")
    # Caller's identity must match supplier_id (PRD §2.1)
    if g.user_id != supplier_id:
        raise err("ERR_FORBIDDEN", "Supplier identity does not match supplier_id.")

    invoice_no = require_string(body["invoice_no"], "invoice_no")
    if any(i.get("supplier_id") == supplier_id and i.get("invoice_no") == invoice_no
           for i in db.invoices.values()):
        raise err("ERR_VALIDATION",
                  "invoice_no must be unique per supplier_id.")
    invoice_date = require_string(body["invoice_date"], "invoice_date")
    try:
        parse_iso(invoice_date)
    except Exception:
        raise err("ERR_VALIDATION", "invoice_date must be ISO 8601.")
    invoiced_quantity = require_int(body["invoiced_quantity"], "invoiced_quantity", min_value=1)
    invoiced_amount = require_int(body["invoiced_amount_cents"], "invoiced_amount_cents", min_value=1)
    tax_amt = require_int(body["tax_amount_cents"], "tax_amount_cents", min_value=0)
    tax_rate = require_number(body["tax_rate_declared"], "tax_rate_declared",
                              min_value=0, max_value=1)

    invoice = {
        "purchase_order_id": po_id,
        "supplier_id": supplier_id,
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "invoiced_quantity": invoiced_quantity,
        "invoiced_amount_cents": invoiced_amount,
        "tax_amount_cents": tax_amt,
        "tax_rate_declared": float(tax_rate),
        "status": "SUBMITTED",
        "matching_result": None,
    }
    stamp_create(invoice, common=True)
    db.invoices[invoice["id"]] = invoice
    return jsonify(success_object(serialize(invoice))), 201


@bp.post("/invoices/<rid>/match")
@require_roles("FinanceApprover")
def match_invoice(rid: str):
    inv = find_invoice(rid)
    enforce_role()
    if inv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Invoice is not SUBMITTED.")
    po = db.purchase_orders.get(inv["purchase_order_id"])
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")
    if po["status"] not in ("CONTRACTED", "FULFILLED"):
        raise err("ERR_INVALID_STATE", "Bound PO is not CONTRACTED/FULFILLED.")

    requirement = db.requirements.get(po["requirement_id"])
    if requirement is None:
        raise err("ERR_NOT_FOUND", "Parent requirement not found.")
    receipts = [
        r for r in db.receipts.values()
        if r.get("purchase_order_id") == po["id"]
        and r.get("status") in ("ACCEPTED", "PARTIALLY_ACCEPTED")
    ]

    result = three_way_match(inv, po, requirement, receipts)
    inv["matching_result"] = result

    # Determine outcome with priority: tax check (priority 15) before quantity/amount (16)
    if not result["tax_compliant"]:
        inv["status"] = "EXCEPTION"
        stamp_update(inv)
        raise err("ERR_TAX_NONCOMPLIANT",
                  "Invoice tax is not compliant.")
    if not (result["quantity_match"] and result["amount_match"]):
        inv["status"] = "EXCEPTION"
        stamp_update(inv)
        raise err("ERR_THREE_WAY_MATCH_FAILED",
                  "Three-way match failed for quantity or amount.")

    inv["status"] = "MATCHED"
    stamp_update(inv)
    return jsonify(success_object(serialize(inv))), 200


@bp.post("/invoices/<rid>/override")
@require_roles("GeneralManager")
def override_invoice(rid: str):
    inv = find_invoice(rid)
    enforce_role()
    body = get_json_body()
    justification = require_string(body.get("justification", ""), "justification")
    if inv["status"] != "EXCEPTION":
        raise err("ERR_INVALID_STATE", "Invoice is not EXCEPTION.")
    inv["status"] = "MATCHED"
    mr = inv.get("matching_result") or {}
    mr["override_by"] = g.user_id
    mr["override_justification"] = justification
    mr["tax_compliant"] = True  # Override forces matched/tax-compliant
    inv["matching_result"] = mr
    stamp_update(inv)
    return jsonify(success_object(serialize(inv))), 200


@bp.post("/invoices/<rid>/approve")
@require_roles("FinanceApprover")
def approve_invoice(rid: str):
    inv = find_invoice(rid)
    enforce_role()
    if inv["status"] != "MATCHED":
        raise err("ERR_INVALID_STATE", "Invoice is not MATCHED.")
    mr = inv.get("matching_result") or {}
    if not mr.get("tax_compliant"):
        raise err("ERR_INVALID_STATE", "Invoice is not tax-compliant.")
    inv["status"] = "APPROVED"
    stamp_update(inv)
    return jsonify(success_object(serialize(inv))), 200


@bp.post("/invoices/<rid>/reject")
@require_roles("FinanceApprover")
def reject_invoice(rid: str):
    inv = find_invoice(rid)
    enforce_role()
    body = get_json_body()
    reason = require_string(body.get("reason", ""), "reason")
    if inv["status"] != "EXCEPTION":
        raise err("ERR_INVALID_STATE", "Invoice is not EXCEPTION.")
    inv["status"] = "REJECTED"
    inv["rejection_reason"] = reason
    stamp_update(inv)
    return jsonify(success_object(serialize(inv))), 200


@bp.get("/invoices/<rid>")
@require_roles("Buyer", "FinanceApprover", "Supplier", "GeneralManager")
def get_invoice(rid: str):
    inv = find_invoice(rid)
    enforce_role()
    if g.user_role == "Supplier":
        if g.user_id != inv.get("supplier_id"):
            raise err("ERR_FORBIDDEN", "Supplier may only view their own invoices.")
    return jsonify(success_object(serialize(inv))), 200
