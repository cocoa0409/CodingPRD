"""Proof routes (PRD §3.4)."""

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services.ownership import require_order_owner
from services.common import (
    get_body, require_fields, require_str, lookup, list_collection,
)

bp = Blueprint("proofs", __name__)


@bp.post("/proofs")
@require_roles("ProductionOperator")
def submit_proof():
    body = get_body()
    require_fields(body, "order_line_id")
    order_line_id = require_str(body, "order_line_id")
    line = lookup(db.order_lines, order_line_id)
    product = db.products[line["product_id"]]

    # State (5) before business checks (PRD §3.9): line must be PREFLIGHT_OK.
    if line["status"] != "PREFLIGHT_OK":
        raise err(errors.ERR_INVALID_STATE,
                  "Proof can only be submitted for a PREFLIGHT_OK line")
    # Product must require a proof, else ERR_PROOF_NOT_REQUIRED (409).
    if not product["requires_proof"]:
        raise err(errors.ERR_PROOF_NOT_REQUIRED,
                  "Product does not require a proof")

    # round_number = prior round + 1 for this line, else 1.
    prior = [p for p in db.proofs.values() if p["order_line_id"] == order_line_id]
    round_number = (max(p["round_number"] for p in prior) + 1) if prior else 1

    rec = {
        "order_line_id": order_line_id,
        "round_number": round_number,
        "status": "SUBMITTED",
        "change_note": None,
    }
    db.stamp_new(rec)
    db.proofs[rec["id"]] = rec

    # Line PREFLIGHT_OK -> PROOF_PENDING.
    line["status"] = "PROOF_PENDING"
    db.touch(line)

    return object_response(serialize.proof(rec), 201)


@bp.get("/proofs")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_proofs():
    order_line_id = request.args.get("order_line_id")
    items, limit, offset, total = list_collection(
        db.proofs,
        (lambda r: r["order_line_id"] == order_line_id) if order_line_id else None)
    return array_response([serialize.proof(r) for r in items], limit, offset, total)


@bp.get("/proofs/<proof_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_proof(proof_id):
    rec = lookup(db.proofs, proof_id)
    return object_response(serialize.proof(rec), 200)


@bp.post("/proofs/<proof_id>/approve")
@require_roles("Customer")
def approve_proof(proof_id):
    proof = lookup(db.proofs, proof_id)
    line = lookup(db.order_lines, proof["order_line_id"])
    order = lookup(db.orders, line["order_id"])
    # Ownership (403) before state (409).
    require_order_owner(order)

    if proof["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Only a SUBMITTED proof may be approved")

    proof["status"] = "APPROVED"
    db.touch(proof)
    # Line PROOF_PENDING -> PROOF_APPROVED.
    line["status"] = "PROOF_APPROVED"
    db.touch(line)
    return object_response(serialize.proof(proof), 200)


@bp.post("/proofs/<proof_id>/request-changes")
@require_roles("Customer")
def request_changes(proof_id):
    proof = lookup(db.proofs, proof_id)
    line = lookup(db.order_lines, proof["order_line_id"])
    order = lookup(db.orders, line["order_id"])
    require_order_owner(order)

    if proof["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE,
                  "Only a SUBMITTED proof may have changes requested")

    body = get_body()
    change_note = body.get("change_note")
    if change_note is None or change_note == "":
        raise err(errors.ERR_CHANGE_NOTE_REQUIRED, "change_note is required")

    proof["status"] = "CHANGES_REQUESTED"
    proof["change_note"] = change_note
    db.touch(proof)
    # Line PROOF_PENDING -> PREFLIGHT_OK (reopened for a new round).
    line["status"] = "PREFLIGHT_OK"
    db.touch(line)
    return object_response(serialize.proof(proof), 200)
