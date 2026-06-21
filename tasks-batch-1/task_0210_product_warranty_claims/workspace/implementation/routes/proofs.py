"""Proof-of-purchase endpoints (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND
from middleware import require_roles
from response import ok_array, ok_object
from services import calc, common
from services.registration_svc import bump, mint_common, public
from services.timeutil import parse_iso

bp = Blueprint("proofs", __name__)

DOCUMENT_TYPES = {"RECEIPT", "INVOICE", "BANK_STATEMENT"}


@bp.post("/proofs")
def submit_proof():
    require_roles(["Owner", "WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["registration_id", "document_type",
                                 "stated_purchase_date", "stated_amount_cents"])
    registration_id = common.require_str(body, "registration_id")
    document_type = common.require_enum(body, "document_type", DOCUMENT_TYPES)
    stated_purchase_date = common.require_str(body, "stated_purchase_date")
    stated_amount_cents = common.require_int(body, "stated_amount_cents", minimum=0)
    try:
        parse_iso(stated_purchase_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "stated_purchase_date must be ISO 8601")

    if registration_id not in db.registrations:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")

    proof = {
        "registration_id": registration_id,
        "document_type": document_type,
        "stated_purchase_date": stated_purchase_date,
        "stated_amount_cents": stated_amount_cents,
        "status": "SUBMITTED",
        "rejection_reason": None,
    }
    mint_common(proof)
    db.proofs[proof["id"]] = proof
    return ok_object(public(proof), 201)


@bp.post("/proofs/<pid>/validate")
def validate_proof(pid):
    require_roles(["WarrantyAdmin"])
    proof = db.proofs.get(pid)
    if proof is None:
        raise APIError(ERR_NOT_FOUND, 404, "ProofOfPurchase not found")
    if proof["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Proof is not SUBMITTED")
    reg = db.registrations.get(proof["registration_id"])
    if reg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")

    # Checks: date within VALIDATION_WINDOW_DAYS; |amount diff| <= tolerance.
    # rejection_reason ordering: date checked before amount (PRD §3.3).
    reg_purchase = parse_iso(reg["purchase_date"])
    stated_date = parse_iso(proof["stated_purchase_date"])
    delta_days = abs((stated_date - reg_purchase).total_seconds()) / 86400.0
    date_ok = delta_days <= calc.VALIDATION_WINDOW_DAYS
    amount_ok = abs(proof["stated_amount_cents"] - reg["purchase_price_cents"]) <= calc.AMOUNT_TOLERANCE_CENTS

    if date_ok and amount_ok:
        proof["status"] = "VALIDATED"
        proof["rejection_reason"] = None
        reg["proof_status"] = "VALIDATED"
        # cross-entity bubble-up: REGISTERED -> ACTIVE on validated proof
        if reg["status"] == "REGISTERED":
            reg["status"] = "ACTIVE"
    else:
        proof["status"] = "REJECTED"
        if not date_ok:
            proof["rejection_reason"] = "DATE_MISMATCH"
        else:
            proof["rejection_reason"] = "AMOUNT_MISMATCH"
        reg["proof_status"] = "REJECTED"

    bump(proof)
    bump(reg)
    return ok_object(public(proof))


@bp.get("/proofs/<pid>")
def get_proof(pid):
    require_roles(["WarrantyAdmin", "Owner"])
    proof = db.proofs.get(pid)
    if proof is None:
        raise APIError(ERR_NOT_FOUND, 404, "ProofOfPurchase not found")
    return ok_object(public(proof))


@bp.get("/proofs")
def list_proofs():
    require_roles(["WarrantyAdmin", "Owner"])
    limit, offset = common.parse_pagination()
    registration_id = request.args.get("registration_id")
    rows = list(db.proofs.values())
    if registration_id is not None:
        rows = [p for p in rows if p["registration_id"] == registration_id]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(p) for p in page], limit, offset, total)
