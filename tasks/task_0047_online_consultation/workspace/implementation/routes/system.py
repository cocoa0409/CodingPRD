"""System / test-harness endpoints: clock advance and event ingest."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_role
from response import success
from errors import (
    AppError,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_BUREAU_EVENT,
    ERR_INSURANCE_INVARIANT_VIOLATION,
)
from config import ROLE_ADMIN
from services.serializers import serialize
from services.audit import append_audit


bp = Blueprint("system", __name__, url_prefix="/consultation")


@bp.post("/_test/reset")
def test_reset():
    """Test-only hook to wipe all in-memory state. Not part of PRD §4."""
    require_role(ROLE_ADMIN)
    db.reset_all()
    return success({}, 200)


@bp.post("/_clock/advance")
def clock_advance():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds", 0)
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise AppError(ERR_INVALID_STATE, "seconds must be a number.", 409)
    db.advance_clock(seconds)
    return success({"current_time": db.now_iso()}, 200)


_DISPENSING_SEQ = ["RECEIVED", "PREPARING", "READY", "DELIVERED"]


def _step_dispensing(current):
    """Advance dispensing_status one step along the sequence; returns next step."""
    if not current or current == "NONE":
        return "RECEIVED"
    if current in _DISPENSING_SEQ:
        idx = _DISPENSING_SEQ.index(current)
        if idx < len(_DISPENSING_SEQ) - 1:
            return _DISPENSING_SEQ[idx + 1]
        return current
    return current


def _handle_pharmacy_dispensed(payload):
    rx_id = payload.get("prescription_id")
    rx = db.find_by_id("prescriptions", rx_id)
    if not rx:
        raise AppError(ERR_INVALID_STATE, "prescription not found.", 409)
    if rx.get("status") != "DISPATCHED":
        raise AppError(ERR_INVALID_STATE, "prescription not DISPATCHED.", 409)
    cur = rx.get("dispensing_status") or "NONE"
    # Explicit target step may be in payload
    target = payload.get("dispensing_status")
    if target:
        next_status = target
    else:
        next_status = _step_dispensing(cur)
    updates = {"dispensing_status": next_status}
    if next_status == "DELIVERED":
        updates["status"] = "DISPENSED"
    rx = db.update("prescriptions", rx_id, updates)
    if next_status == "DELIVERED":
        append_audit("PRESCRIPTION_DISPENSED", "Prescription", rx_id, payload)
    return rx


def _handle_pharmacy_failed(payload):
    rx_id = payload.get("prescription_id")
    rx = db.find_by_id("prescriptions", rx_id)
    if not rx:
        raise AppError(ERR_INVALID_STATE, "prescription not found.", 409)
    if rx.get("status") != "DISPATCHED":
        raise AppError(ERR_INVALID_STATE, "prescription not DISPATCHED.", 409)
    rx = db.update("prescriptions", rx_id, {
        "status": "FAILED",
        "dispensing_status": "FAILED",
    })
    append_audit("PRESCRIPTION_FAILED", "Prescription", rx_id, payload)
    return rx


def _handle_bureau_settled(payload):
    claim_id = payload.get("claim_id")
    bureau_ref = payload.get("bureau_ref")
    claim = db.find_by_id("insurance_claims", claim_id)
    if not claim:
        raise AppError(ERR_INVALID_STATE, "claim not found.", 409)
    # Idempotency: (claim_id, kind, bureau_ref)
    for prior in db.all_rows("bureau_event_dedup"):
        if (
            prior.get("claim_id") == claim_id
            and prior.get("kind") == "BUREAU_SETTLED"
            and prior.get("bureau_ref") == bureau_ref
        ):
            raise AppError(ERR_DUPLICATE_BUREAU_EVENT, "Duplicate BUREAU_SETTLED.", 409)
    if claim.get("status") != "SETTLING":
        raise AppError(ERR_INVALID_STATE, "claim not SETTLING.", 409)
    # Invariant check
    ca = int(claim.get("claim_amount_cents") or 0)
    reim = int(claim.get("reimbursed_cents") or 0)
    sp = int(claim.get("self_pay_cents") or 0)
    if ca != reim + sp:
        raise AppError(
            ERR_INSURANCE_INVARIANT_VIOLATION,
            "claim_amount_cents != reimbursed + self_pay",
            422,
        )
    claim = db.update("insurance_claims", claim_id, {
        "status": "SETTLED",
        "bureau_ref": bureau_ref,
    })
    db.insert("bureau_event_dedup", {
        "claim_id": claim_id,
        "kind": "BUREAU_SETTLED",
        "bureau_ref": bureau_ref,
    }, with_version=False)
    append_audit("CLAIM_SETTLED", "InsuranceClaim", claim_id, payload)
    return claim


def _handle_bureau_rejected(payload):
    claim_id = payload.get("claim_id")
    claim = db.find_by_id("insurance_claims", claim_id)
    if not claim:
        raise AppError(ERR_INVALID_STATE, "claim not found.", 409)
    if claim.get("status") != "SETTLING":
        raise AppError(ERR_INVALID_STATE, "claim not SETTLING.", 409)
    full = int(claim.get("claim_amount_cents") or 0)
    claim = db.update("insurance_claims", claim_id, {
        "status": "REJECTED_BY_BUREAU",
        "reimbursed_cents": 0,
        "self_pay_cents": full,
    })
    return claim


def _handle_payment_confirmed(payload):
    claim_id = payload.get("claim_id")
    claim = db.find_by_id("insurance_claims", claim_id)
    if not claim:
        raise AppError(ERR_INVALID_STATE, "claim not found.", 409)
    claim = db.update("insurance_claims", claim_id, {
        "self_pay_collected_cents": int(claim.get("self_pay_cents") or 0),
    })
    return claim


@bp.post("/_events/emit")
def emit_event():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    payload = body.get("payload") or {}
    if kind == "PHARMACY_DISPENSED":
        result = _handle_pharmacy_dispensed(payload)
    elif kind == "PHARMACY_FAILED":
        result = _handle_pharmacy_failed(payload)
    elif kind == "BUREAU_SETTLED":
        result = _handle_bureau_settled(payload)
    elif kind == "BUREAU_REJECTED":
        result = _handle_bureau_rejected(payload)
    elif kind == "PAYMENT_CONFIRMED":
        result = _handle_payment_confirmed(payload)
    else:
        raise AppError(ERR_INVALID_STATE, f"Unknown event kind {kind}.", 409)
    return success(serialize(result) if result else {}, 200)
