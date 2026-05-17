"""Insurance claim routes."""
from flask import Blueprint, jsonify, request

from app.auth import require_roles
from app.errors import err_invalid_state, err_not_found
from app.responses import success_object
from app.store import store
from app.utils import bump_version_and_timestamp, check_version_if_supplied, parse_json_body


bp = Blueprint("claims", __name__)


@bp.get("/telemed/claims/<cid>")
@require_roles(["ComplianceOfficer", "Payer"])
def get_claim(cid: str):
    claim = store.claims.get(cid)
    if not claim:
        raise err_not_found()
    return jsonify(success_object(claim)), 200


@bp.post("/telemed/claims/<cid>/approve")
@require_roles(["Payer"])
def approve_claim(cid: str):
    claim = store.claims.get(cid)
    if not claim:
        raise err_not_found()
    body = parse_json_body()
    if claim["status"] not in {"SUBMITTED", "APPEALED"}:
        raise err_invalid_state("Claim cannot be approved from its current state")
    check_version_if_supplied(claim, body)
    with store.lock:
        if claim["status"] not in {"SUBMITTED", "APPEALED"}:
            raise err_invalid_state("Claim cannot be approved from its current state")
        claim["status"] = "APPROVED"
        bump_version_and_timestamp(claim, store.now_iso())
    return jsonify(success_object(claim)), 200


@bp.post("/telemed/claims/<cid>/deny")
@require_roles(["Payer"])
def deny_claim(cid: str):
    claim = store.claims.get(cid)
    if not claim:
        raise err_not_found()
    body = parse_json_body()
    if claim["status"] != "SUBMITTED":
        raise err_invalid_state("Only SUBMITTED claims can be denied")
    check_version_if_supplied(claim, body)
    denial_reason = body.get("denial_reason")
    if not isinstance(denial_reason, str) or not denial_reason:
        raise err_invalid_state("denial_reason is required")
    with store.lock:
        if claim["status"] != "SUBMITTED":
            raise err_invalid_state("Only SUBMITTED claims can be denied")
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        bump_version_and_timestamp(claim, store.now_iso())
    return jsonify(success_object(claim)), 200


@bp.post("/telemed/claims/<cid>/appeal")
@require_roles(["ComplianceOfficer"])
def appeal_claim(cid: str):
    claim = store.claims.get(cid)
    if not claim:
        raise err_not_found()
    body = parse_json_body()
    if claim["status"] != "DENIED":
        raise err_invalid_state("Only DENIED claims can be appealed")
    check_version_if_supplied(claim, body)
    with store.lock:
        if claim["status"] != "DENIED":
            raise err_invalid_state("Only DENIED claims can be appealed")
        claim["status"] = "APPEALED"
        bump_version_and_timestamp(claim, store.now_iso())
    return jsonify(success_object(claim)), 200


@bp.post("/telemed/claims/<cid>/mark-paid")
@require_roles(["Payer"])
def mark_paid(cid: str):
    claim = store.claims.get(cid)
    if not claim:
        raise err_not_found()
    body = parse_json_body()
    if claim["status"] != "APPROVED":
        raise err_invalid_state("Only APPROVED claims can be marked paid")
    check_version_if_supplied(claim, body)

    actor_role = request.headers.get("X-User-Role", "Payer")

    with store.lock:
        if claim["status"] != "APPROVED":
            raise err_invalid_state("Only APPROVED claims can be marked paid")
        # payer_paid = billed - patient_responsibility
        claim["payer_paid_cents"] = max(
            0, claim["billed_cents"] - claim["patient_responsibility_cents"]
        )
        claim["status"] = "PAID"
        bump_version_and_timestamp(claim, store.now_iso())

        # Decrement patient deductible by deductible_applied_cents, floored at 0.
        consult = store.consults.get(claim["consult_id"])
        if consult:
            patient = store.patients.get(consult["patient_id"])
            if patient:
                prev = int(patient.get("insurance_deductible_remaining_cents", 0))
                applied = int(claim["deductible_applied_cents"])
                patient["insurance_deductible_remaining_cents"] = max(0, prev - applied)
                bump_version_and_timestamp(patient, store.now_iso())

        store.append_audit(
            event_type="CLAIM_PAID",
            subject_entity="InsuranceClaim",
            subject_id=claim["id"],
            actor_role=actor_role,
            payload_json={
                "consult_id": claim["consult_id"],
                "payer_paid_cents": claim["payer_paid_cents"],
                "deductible_applied_cents": claim["deductible_applied_cents"],
            },
        )
    return jsonify(success_object(claim)), 200
