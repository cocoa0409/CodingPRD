"""PurchaseOrder endpoints (PRD §3.5 cancel; lookup/list)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db, stamp_update, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.approval import steps_for_po
from services.lookups import find_purchase_order

bp = Blueprint("purchase_orders", __name__)


@bp.get("/purchase-orders/<rid>")
@require_roles("Buyer", "Requester", "FinanceApprover", "DepartmentHead", "GeneralManager", "LegalApprover")
def get_po(rid: str):
    row = find_purchase_order(rid)
    enforce_role()
    return jsonify(success_object(serialize(row))), 200


@bp.post("/purchase-orders/<rid>/cancel")
@require_roles("Buyer")
def cancel_po(rid: str):
    po = find_purchase_order(rid)
    enforce_role()
    if po["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE", "PurchaseOrder is not PENDING_APPROVAL.")
    # Only when no ApprovalStep has been decided
    for s in steps_for_po(po["id"]):
        if s.get("decided_at") is not None:
            raise err("ERR_INVALID_STATE",
                      "Cannot cancel: an ApprovalStep has already been decided.")
    po["status"] = "CANCELLED"
    stamp_update(po)
    # Skip every approval step
    for s in steps_for_po(po["id"]):
        if s.get("status") == "PENDING":
            s["status"] = "SKIPPED"
    # Release commitment
    ba = db.budget_accounts.get(po["budget_account_id"])
    if ba is not None:
        ba["committed_amount_cents"] -= int(po["total_amount_cents"])
        stamp_update(ba)
    return jsonify(success_object(serialize(po))), 200


@bp.get("/purchase-orders")
@require_roles("Buyer", "FinanceApprover", "GeneralManager")
def list_pos():
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    tier = request.args.get("tier")
    supplier_id = request.args.get("supplier_id")
    rows = list(db.purchase_orders.values())
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if tier is not None:
        rows = [r for r in rows if r.get("tier") == tier]
    if supplier_id is not None:
        rows = [r for r in rows if r.get("supplier_id") == supplier_id]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200
