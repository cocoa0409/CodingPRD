"""Payout batch routes."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from db import db, gen_id
from errors import (
    ERR_BATCH_ALREADY_DISPATCHED,
    ERR_BATCH_FLIGHT_MISMATCH,
    ERR_BATCH_NOT_APPROVED,
    ERR_CLAIM_NOT_APPROVED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    raise_api_error,
)
from middleware import require_roles
from response import success_response
from services.common import (
    append_audit,
    check_version,
    emit_outbox,
    get_batch_or_404,
    get_flight_or_404,
    get_insurer_or_404,
    get_json_body,
    require_field,
)

bp = Blueprint("payout_batches", __name__)


def _serialize_batch(b: dict) -> dict:
    return dict(b)


@bp.post("/insurers/<insurer_id>/payout_batches")
@require_roles("BatchApprover", "ClaimsAdmin")
def create_batch(insurer_id: str):
    get_insurer_or_404(insurer_id)
    body = get_json_body()
    flight_id = require_field(body, "flight_id", type_=str)
    claim_ids = require_field(body, "claim_ids", type_=list)

    flight = get_flight_or_404(insurer_id, flight_id)

    claims = []
    for cid in claim_ids:
        if not isinstance(cid, str):
            raise_api_error(ERR_INVALID_REQUEST, "claim_ids must be strings.")
        c = db.claims.get(cid)
        if not c or c.get("insurer_id") != insurer_id:
            raise_api_error(ERR_NOT_FOUND, f"Claim {cid} not found.")
        claims.append(c)

    # Each claim must be APPROVED + PAYABLE and have a segment with flight_id matching the batch
    for c in claims:
        if c.get("review_status") != "APPROVED":
            raise_api_error(ERR_CLAIM_NOT_APPROVED, f"Claim {c['id']} is not APPROVED.")
        if c.get("payout_status") != "PAYABLE":
            raise_api_error(ERR_INVALID_STATE,
                            f"Claim {c['id']} payout_status is {c.get('payout_status')}.")
        seg_flights = {db.claim_segments[s].get("flight_id") for s in c.get("segment_ids", [])}
        if flight_id not in seg_flights:
            raise_api_error(ERR_BATCH_FLIGHT_MISMATCH,
                            f"Claim {c['id']} has no segment on flight {flight_id}.")
        if c.get("payout_batch_id"):
            raise_api_error(ERR_INVALID_STATE,
                            f"Claim {c['id']} is already in a batch.")

    total_planned = sum((c.get("estimated_payout_cents", 0) or 0) for c in claims)
    batch = {
        "id": gen_id(),
        "insurer_id": insurer_id,
        "flight_id": flight_id,
        "claim_ids": [c["id"] for c in claims],
        "review_phase": "STAGED",
        "execution_phase": "PENDING",
        "total_planned_payout_cents": total_planned,
        "total_settled_payout_cents": 0,
        "exception_claim_ids": [],
        "assigned_batch_approver_id": None,
        "assigned_batch_executor_id": None,
    }
    db.stamp_create(batch)
    db.payout_batches[batch["id"]] = batch

    for c in claims:
        c["payout_batch_id"] = batch["id"]
        db.stamp_update(c)

    append_audit(insurer_id, "PAYOUT_BATCH", batch["id"], "STATUS_CHANGE",
                 {"to": "STAGED", "claim_count": len(claims),
                  "total_planned_payout_cents": total_planned})
    return jsonify(success_response(_serialize_batch(batch))), 201


@bp.get("/insurers/<insurer_id>/payout_batches/<batch_id>")
@require_roles("Any")
def get_batch(insurer_id: str, batch_id: str):
    get_insurer_or_404(insurer_id)
    b = get_batch_or_404(insurer_id, batch_id)
    return jsonify(success_response(_serialize_batch(b))), 200


@bp.post("/insurers/<insurer_id>/payout_batches/<batch_id>/approve")
@require_roles("BatchApprover")
def approve_batch(insurer_id: str, batch_id: str):
    get_insurer_or_404(insurer_id)
    b = get_batch_or_404(insurer_id, batch_id)
    body = get_json_body()
    check_version(body, b)
    assigned = require_field(body, "assigned_batch_approver_id", type_=str)

    if b["review_phase"] != "STAGED":
        raise_api_error(ERR_INVALID_STATE, f"Batch review_phase is {b['review_phase']}.")

    # Each claim still APPROVED
    for cid in b["claim_ids"]:
        c = db.claims.get(cid)
        if not c or c.get("review_status") != "APPROVED":
            raise_api_error(ERR_CLAIM_NOT_APPROVED, f"Claim {cid} is not APPROVED.")

    # SoD: batch approver cannot equal any per-claim approver
    for cid in b["claim_ids"]:
        c = db.claims[cid]
        if c.get("assigned_approver_id") and assigned == c["assigned_approver_id"]:
            raise_api_error(ERR_SOD_VIOLATION,
                            "Batch approver cannot equal any per-claim approver.")
    if assigned != g.user_id:
        raise_api_error(ERR_INVALID_REQUEST, "assigned_batch_approver_id must equal X-User-ID.")

    b["assigned_batch_approver_id"] = assigned
    b["review_phase"] = "APPROVED"
    db.stamp_update(b)
    append_audit(insurer_id, "PAYOUT_BATCH", b["id"], "STATUS_CHANGE",
                 {"from": "STAGED", "to": "APPROVED"})
    return jsonify(success_response(_serialize_batch(b))), 200


@bp.post("/insurers/<insurer_id>/payout_batches/<batch_id>/reject")
@require_roles("BatchApprover")
def reject_batch(insurer_id: str, batch_id: str):
    get_insurer_or_404(insurer_id)
    b = get_batch_or_404(insurer_id, batch_id)
    body = get_json_body()
    check_version(body, b)
    require_field(body, "reason", type_=str)

    if b["review_phase"] != "STAGED":
        raise_api_error(ERR_INVALID_STATE, f"Batch review_phase is {b['review_phase']}.")

    b["review_phase"] = "REJECTED"
    db.stamp_update(b)
    append_audit(insurer_id, "PAYOUT_BATCH", b["id"], "STATUS_CHANGE",
                 {"from": "STAGED", "to": "REJECTED", "reason": body["reason"]})
    return jsonify(success_response(_serialize_batch(b))), 200


@bp.post("/insurers/<insurer_id>/payout_batches/<batch_id>/execute")
@require_roles("BatchExecutor")
def execute_batch(insurer_id: str, batch_id: str):
    get_insurer_or_404(insurer_id)
    b = get_batch_or_404(insurer_id, batch_id)
    body = get_json_body()
    check_version(body, b)
    assigned = require_field(body, "assigned_batch_executor_id", type_=str)

    if b["review_phase"] != "APPROVED":
        raise_api_error(ERR_BATCH_NOT_APPROVED, "Batch review_phase is not APPROVED.")
    if b["execution_phase"] != "PENDING":
        raise_api_error(ERR_BATCH_ALREADY_DISPATCHED,
                        f"Batch is already in {b['execution_phase']}.")

    if assigned != g.user_id:
        raise_api_error(ERR_INVALID_REQUEST, "assigned_batch_executor_id must equal X-User-ID.")
    if b.get("assigned_batch_approver_id") and assigned == b["assigned_batch_approver_id"]:
        raise_api_error(ERR_SOD_VIOLATION,
                        "Batch executor cannot equal batch approver.")

    # SoD: per-claim approver cannot equal this operator
    for cid in b["claim_ids"]:
        c = db.claims.get(cid)
        if c and c.get("assigned_approver_id") and assigned == c["assigned_approver_id"]:
            raise_api_error(ERR_SOD_VIOLATION,
                            "Batch executor cannot equal a per-claim approver.")

    b["assigned_batch_executor_id"] = assigned
    b["execution_phase"] = "EXECUTING"
    db.stamp_update(b)

    for cid in b["claim_ids"]:
        c = db.claims[cid]
        if c.get("payout_status") == "PAYABLE":
            c["payout_status"] = "EXECUTING"
            c["payout_operator_id"] = assigned
            db.stamp_update(c)
            emit_outbox(insurer_id, "BANKING", "BATCH_DISPATCHED", "CLAIM", c["id"],
                        {"claim_id": c["id"], "amount_cents": c.get("estimated_payout_cents", 0) or 0,
                         "batch_id": b["id"]})
            append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                         {"from": "PAYABLE", "to": "EXECUTING", "batch_id": b["id"]})

    append_audit(insurer_id, "PAYOUT_BATCH", b["id"], "STATUS_CHANGE",
                 {"from": "PENDING", "to": "EXECUTING"})
    return jsonify(success_response(_serialize_batch(b))), 200


@bp.post("/insurers/<insurer_id>/payout_batches/<batch_id>/retry_exceptions")
@require_roles("BatchExecutor")
def retry_exceptions(insurer_id: str, batch_id: str):
    get_insurer_or_404(insurer_id)
    b = get_batch_or_404(insurer_id, batch_id)
    body = get_json_body()
    check_version(body, b)

    if b["execution_phase"] != "EXCEPTIONS":
        raise_api_error(ERR_INVALID_STATE,
                        f"Batch execution_phase is {b['execution_phase']}.")

    exceptions = list(b.get("exception_claim_ids") or [])
    for cid in exceptions:
        c = db.claims.get(cid)
        if c and c.get("payout_status") == "PAYABLE":
            c["payout_status"] = "EXECUTING"
            db.stamp_update(c)
            emit_outbox(insurer_id, "BANKING", "BATCH_DISPATCHED", "CLAIM", c["id"],
                        {"claim_id": c["id"], "amount_cents": c.get("estimated_payout_cents", 0) or 0,
                         "batch_id": b["id"], "retry": True})
            append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                         {"from": "PAYABLE", "to": "EXECUTING", "retry": True})

    b["exception_claim_ids"] = []
    b["execution_phase"] = "EXECUTING"
    db.stamp_update(b)
    append_audit(insurer_id, "PAYOUT_BATCH", b["id"], "STATUS_CHANGE",
                 {"from": "EXCEPTIONS", "to": "EXECUTING"})
    return jsonify(success_response(_serialize_batch(b))), 200
