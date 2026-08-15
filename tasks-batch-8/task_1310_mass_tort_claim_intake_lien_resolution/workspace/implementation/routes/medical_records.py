"""Medical record CRUD + review transitions."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_RECORD_ALREADY_REVIEWED,
    ERR_INSUFFICIENT_MEDICAL_RECORDS,
    ERR_NO_QUALIFYING_RECORD,
)
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_claim,
    resolve_medical_record,
    sort_by_created_at,
    utc_now_iso,
)

bp = Blueprint("medical_records", __name__)

RECORD_READ_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
)

VALID_RECORD_TYPES = {"DIAGNOSTIC", "TREATMENT", "PHARMACY", "HOSPITALIZATION"}


@bp.route("/settlement-programs/<pid>/claims/<cid>/medical-records", methods=["POST"])
def create_medical_record(pid, cid):
    user_id, role = require_role("RecordsAnalyst")
    prog, claim = resolve_claim(pid, cid)

    # PRD §3.3 gates accept/reject/verify on the claim state, but names no
    # claim-state gate for upload itself ("Once a claim has passed eligibility,
    # a RecordsAnalyst uploads medical records one at a time"). The only
    # state-conditioned behavior is the first-upload cascade below.
    body = get_json_body()
    require_fields(body, ["provider_name", "record_type", "severity_score", "confirms_qualifying_injury"])

    rt = body["record_type"]
    if rt not in VALID_RECORD_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "record_type must be one of DIAGNOSTIC, TREATMENT, PHARMACY, HOSPITALIZATION", 400)

    score = body["severity_score"]
    if not isinstance(score, int) or score < 0 or score > 100:
        raise ApiError(ERR_INVALID_REQUEST, "severity_score must be integer 0..100", 400)

    if not isinstance(body["confirms_qualifying_injury"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "confirms_qualifying_injury must be a boolean", 400)

    rec = {
        "claim_id": cid,
        "provider_name": body["provider_name"],
        "record_type": rt,
        "received_at": utc_now_iso(),
        "severity_score": score,
        "confirms_qualifying_injury": body["confirms_qualifying_injury"],
        "review_state": "PENDING_REVIEW",
    }
    rec.update(new_common_fields())
    db.medical_records[rec["id"]] = rec

    # Cascade: first upload against ELIGIBILITY_PASSED advances claim to RECORDS_PENDING
    if claim["status"] == "ELIGIBILITY_PASSED":
        claim["status"] = "RECORDS_PENDING"
        bump(claim)

    return success_envelope(rec, 201, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/medical-records", methods=["GET"])
def list_medical_records(pid, cid):
    user_id, role = require_role(*RECORD_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)
    limit, offset = get_pagination()

    items = [r for r in db.medical_records.values() if r["claim_id"] == cid]

    state_filter = request.args.get("review_state")
    if state_filter:
        items = [r for r in items if r["review_state"] == state_filter]

    claim_filter = request.args.get("claim_id")
    if claim_filter:
        items = [r for r in items if r["claim_id"] == claim_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claims/<cid>/medical-records/<rid>", methods=["GET"])
def get_medical_record(pid, cid, rid):
    user_id, role = require_role(*RECORD_READ_ROLES)
    prog, claim, rec = resolve_medical_record(pid, cid, rid)
    return success_envelope(rec, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/medical-records/<rid>/accept", methods=["POST"])
def accept_record(pid, cid, rid):
    user_id, role = require_role("RecordsAnalyst")
    prog, claim, rec = resolve_medical_record(pid, cid, rid)

    if claim["status"] != "RECORDS_PENDING":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be RECORDS_PENDING", 409)

    if rec["review_state"] != "PENDING_REVIEW":
        raise ApiError(ERR_RECORD_ALREADY_REVIEWED, "Record has already been reviewed", 409)

    rec["review_state"] = "ACCEPTED"
    bump(rec)
    return success_envelope(rec, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/medical-records/<rid>/reject", methods=["POST"])
def reject_record(pid, cid, rid):
    user_id, role = require_role("RecordsAnalyst")
    prog, claim, rec = resolve_medical_record(pid, cid, rid)

    if claim["status"] != "RECORDS_PENDING":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be RECORDS_PENDING", 409)

    if rec["review_state"] != "PENDING_REVIEW":
        raise ApiError(ERR_RECORD_ALREADY_REVIEWED, "Record has already been reviewed", 409)

    rec["review_state"] = "REJECTED"
    bump(rec)
    return success_envelope(rec, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/verify-injury", methods=["POST"])
def verify_injury(pid, cid):
    user_id, role = require_role("RecordsAnalyst")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "RECORDS_PENDING":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be RECORDS_PENDING to verify injury", 409)

    accepted = [
        r for r in db.medical_records.values()
        if r["claim_id"] == cid and r["review_state"] == "ACCEPTED"
    ]

    if len(accepted) < 2:
        raise ApiError(ERR_INSUFFICIENT_MEDICAL_RECORDS, "Fewer than 2 ACCEPTED medical records", 409)

    has_qualifying = any(r["confirms_qualifying_injury"] for r in accepted)
    if not has_qualifying:
        raise ApiError(ERR_NO_QUALIFYING_RECORD, "No ACCEPTED record with confirms_qualifying_injury=true", 422)

    claim["status"] = "INJURY_VERIFIED"
    claim["injury_verification_status"] = "VERIFIED"
    bump(claim)
    return success_envelope(claim, 200, "object")
