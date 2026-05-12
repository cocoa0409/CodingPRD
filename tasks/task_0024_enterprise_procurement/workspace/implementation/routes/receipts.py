"""Receipt endpoints (PRD §3.8)."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import db, stamp_create, stamp_update, serialize
from errors import err
from middleware import enforce_role, require_roles
from response import success_object
from services.calculations import recompute_supplier_rating
from services.lookups import find_purchase_order, find_receipt
from validate import get_json_body, require_fields, require_int, require_number, require_string

bp = Blueprint("receipts", __name__)


def _delivery_note_matches(po_id: str, delivery_note_no: str) -> bool:
    return any(
        d.get("purchase_order_id") == po_id and d.get("delivery_note_no") == delivery_note_no
        for d in db.delivery_notes
    )


@bp.post("/purchase-orders/<rid>/receipts")
@require_roles("Inspector", "Buyer")
def create_receipt(rid: str):
    po = find_purchase_order(rid)
    enforce_role()
    body = get_json_body()
    require_fields(body, ["delivery_note_no", "received_quantity", "accepted_quantity", "quality_rating"])
    delivery_note_no = require_string(body["delivery_note_no"], "delivery_note_no")
    received_quantity = require_int(body["received_quantity"], "received_quantity", min_value=1)
    accepted_quantity = require_int(body["accepted_quantity"], "accepted_quantity", min_value=0)
    if accepted_quantity > received_quantity:
        raise err("ERR_VALIDATION", "accepted_quantity must be <= received_quantity.")
    quality = require_number(body["quality_rating"], "quality_rating", min_value=0, max_value=100)

    receipt = {
        "purchase_order_id": po["id"],
        "supplier_id": po.get("supplier_id"),
        "delivery_note_no": delivery_note_no,
        "received_quantity": received_quantity,
        "accepted_quantity": accepted_quantity,
        "rejected_quantity": received_quantity - accepted_quantity,
        "quality_rating": float(quality),
        "status": "DRAFT",
        "cumulative_accepted_after": None,
    }
    stamp_create(receipt, common=True)
    db.receipts[receipt["id"]] = receipt
    return jsonify(success_object(serialize(receipt))), 201


@bp.post("/receipts/<rid>/inspect")
@require_roles("Inspector")
def inspect_receipt(rid: str):
    r = find_receipt(rid)
    enforce_role()
    po = db.purchase_orders.get(r["purchase_order_id"])
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Receipt is not DRAFT.")
    if po["status"] != "CONTRACTED":
        raise err("ERR_INVALID_STATE", "PurchaseOrder is not CONTRACTED.")
    # Priority 12 — delivery_note_no must match a posted record
    if not _delivery_note_matches(po["id"], r["delivery_note_no"]):
        raise err("ERR_DELIVERY_NOTE_MISMATCH",
                  "delivery_note_no does not match any posted delivery-note for this PO.")
    # accepted_quantity already constrained to received_quantity at create time;
    # re-check defensively.
    if int(r["accepted_quantity"]) > int(r["received_quantity"]):
        raise err("ERR_DELIVERY_NOTE_MISMATCH",
                  "accepted_quantity exceeds received_quantity.")
    r["status"] = "INSPECTING"
    stamp_update(r)
    return jsonify(success_object(serialize(r))), 200


@bp.post("/receipts/<rid>/accept")
@require_roles("Inspector")
def accept_receipt(rid: str):
    r = find_receipt(rid)
    enforce_role()
    if r["status"] != "INSPECTING":
        raise err("ERR_INVALID_STATE", "Receipt is not INSPECTING.")
    po = db.purchase_orders.get(r["purchase_order_id"])
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")

    # Priority 12 — re-check delivery-note (defensive) and accepted <= received
    if not _delivery_note_matches(po["id"], r["delivery_note_no"]):
        raise err("ERR_DELIVERY_NOTE_MISMATCH",
                  "delivery_note_no no longer matches.")
    if int(r["accepted_quantity"]) > int(r["received_quantity"]):
        raise err("ERR_DELIVERY_NOTE_MISMATCH",
                  "accepted_quantity exceeds received_quantity.")

    accepted = int(r["accepted_quantity"])
    received = int(r["received_quantity"])
    quality = float(r["quality_rating"])

    # Determine outcome
    if accepted == 0 or quality < 60:
        # Should be /reject not /accept. Surface invalid-state.
        raise err("ERR_INVALID_STATE",
                  "Receipt does not meet acceptance criteria — use reject instead.")

    # Priority 13 — cumulative <= requirement.quantity
    requirement = db.requirements.get(po["requirement_id"])
    if requirement is None:
        raise err("ERR_NOT_FOUND", "Parent requirement not found.")
    prior_accepted = sum(
        int(x.get("accepted_quantity", 0))
        for x in db.receipts.values()
        if x.get("purchase_order_id") == po["id"]
        and x["id"] != r["id"]
        and x.get("status") in ("ACCEPTED", "PARTIALLY_ACCEPTED")
    )
    cumulative_after = prior_accepted + accepted
    if cumulative_after > int(requirement["quantity"]):
        raise err("ERR_OVER_RECEIPT",
                  "Cumulative accepted quantity would exceed requirement quantity.")

    # Outcome — full vs partial
    if accepted == received:
        r["status"] = "ACCEPTED"
    else:
        r["status"] = "PARTIALLY_ACCEPTED"
    r["cumulative_accepted_after"] = cumulative_after
    stamp_update(r)

    # Supplier rating recompute
    recompute_supplier_rating(po["supplier_id"])

    # Cascade: PO -> FULFILLED if cumulative reaches requirement.quantity
    if cumulative_after == int(requirement["quantity"]) and po["status"] == "CONTRACTED":
        po["status"] = "FULFILLED"
        stamp_update(po)

    return jsonify(success_object(serialize(r))), 200


@bp.post("/receipts/<rid>/reject")
@require_roles("Inspector")
def reject_receipt(rid: str):
    r = find_receipt(rid)
    enforce_role()
    if r["status"] != "INSPECTING":
        raise err("ERR_INVALID_STATE", "Receipt is not INSPECTING.")
    accepted = int(r["accepted_quantity"])
    quality = float(r["quality_rating"])
    if not (accepted == 0 or quality < 60):
        raise err("ERR_INVALID_STATE",
                  "Receipt does not meet rejection criteria.")
    r["status"] = "REJECTED"
    stamp_update(r)
    return jsonify(success_object(serialize(r))), 200


@bp.post("/receipts/<rid>/return")
@require_roles("Inspector")
def return_receipt(rid: str):
    r = find_receipt(rid)
    enforce_role()
    if r["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Receipt is not REJECTED.")
    r["status"] = "RETURNED"
    stamp_update(r)
    return jsonify(success_object(serialize(r))), 200
