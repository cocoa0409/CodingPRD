"""Claim CRUD + state transitions."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_CLAIM_NOT_WITHDRAWABLE,
    ERR_DUPLICATE_ACTIVE_CLAIM,
    ERR_ELIGIBILITY_DATE_ORDER,
    ERR_INELIGIBLE_INJURY,
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
    resolve_program,
    resolve_claim,
    resolve_claimant,
    sort_by_created_at,
)

bp = Blueprint("claims", __name__)

CLAIM_LIST_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
)

CLAIM_READ_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
)

TERMINAL_STATUSES = {"DENIED", "WITHDRAWN", "CLOSED"}


@bp.route("/settlement-programs/<pid>/claims", methods=["POST"])
def create_claim(pid):
    user_id, role = require_role("IntakeSpecialist")
    prog = resolve_program(pid)
    body = get_json_body()
    require_fields(body, ["claimant_id"])

    claimant_id = body["claimant_id"]
    claimant = db.claimants.get(claimant_id)
    if claimant is None or claimant["settlement_program_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, "Claimant not found", 404)

    claim = {
        "settlement_program_id": pid,
        "claimant_id": claimant_id,
        "claim_number": db.next_claim_number(),
        "status": "SUBMITTED",
        "eligibility_status": "PENDING",
        "injury_verification_status": "PENDING",
        "lien_posture": "NOT_STARTED",
        "denied_reason": None,
        "gross_award_cents": 0,
        "total_lien_cents": 0,
        "attorney_fee_cents": 0,
        "net_award_cents": 0,
        "qsf_reservation_cents": 0,
        "active_appeal_id": None,
        "prepare_disbursement_user_id": None,
    }
    claim.update(new_common_fields())
    db.claims[claim["id"]] = claim
    return success_envelope(claim, 201, "object")


@bp.route("/settlement-programs/<pid>/claims", methods=["GET"])
def list_claims(pid):
    user_id, role = require_role(*CLAIM_LIST_ROLES)
    prog = resolve_program(pid)
    limit, offset = get_pagination()

    items = [c for c in db.claims.values() if c["settlement_program_id"] == pid]

    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]

    sp_filter = request.args.get("settlement_program_id")
    if sp_filter:
        items = [c for c in items if c["settlement_program_id"] == sp_filter]

    claimant_filter = request.args.get("claimant_id")
    if claimant_filter:
        items = [c for c in items if c["claimant_id"] == claimant_filter]

    appeal_filter = request.args.get("active_appeal_id")
    if appeal_filter:
        items = [c for c in items if c.get("active_appeal_id") == appeal_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claims/<cid>", methods=["GET"])
def get_claim(pid, cid):
    user_id, role = require_role(*CLAIM_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)

    # ClaimantRole ownership check
    if role == "ClaimantRole" and user_id != claim["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)

    return success_envelope(claim, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/screen-eligibility", methods=["POST"])
def screen_eligibility(pid, cid):
    user_id, role = require_role("IntakeSpecialist")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be SUBMITTED to screen eligibility", 409)

    claimant = db.claimants[claim["claimant_id"]]

    # Check date order: start <= diagnosis <= end
    if not (
        claimant["date_of_exposure_start"] <= claimant["date_of_diagnosis"] <= claimant["date_of_exposure_end"]
    ):
        raise ApiError(ERR_ELIGIBILITY_DATE_ORDER, "date_of_exposure_start <= date_of_diagnosis <= date_of_exposure_end violated", 422)

    # Check injury category
    if claimant["injury_category"] == "NON_QUALIFYING":
        raise ApiError(ERR_INELIGIBLE_INJURY, "injury_category is NON_QUALIFYING", 422)

    # Check for duplicate active claims
    for other in db.claims.values():
        if (
            other["claimant_id"] == claimant["id"]
            and other["id"] != claim["id"]
            and other["status"] not in TERMINAL_STATUSES
        ):
            raise ApiError(ERR_DUPLICATE_ACTIVE_CLAIM, "Another claim for same claimant is in a non-terminal state", 409)

    claim["status"] = "ELIGIBILITY_PASSED"
    claim["eligibility_status"] = "PASSED"
    bump(claim)
    return success_envelope(claim, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/deny", methods=["POST"])
def deny_claim(pid, cid):
    user_id, role = require_role("IntakeSpecialist")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be SUBMITTED to deny", 409)

    body = get_json_body()
    require_fields(body, ["denied_reason"])
    reason = body["denied_reason"]
    if not isinstance(reason, str) or len(reason.strip()) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "denied_reason must be non-empty", 400)

    claim["status"] = "DENIED"
    claim["eligibility_status"] = "FAILED"
    claim["denied_reason"] = reason
    bump(claim)
    return success_envelope(claim, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(pid, cid):
    user_id, role = require_role("ClaimantRole")
    prog, claim = resolve_claim(pid, cid)

    # ClaimantRole ownership check
    if user_id != claim["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)

    if claim["status"] not in ("SUBMITTED", "ELIGIBILITY_PASSED", "RECORDS_PENDING", "INJURY_VERIFIED"):
        raise ApiError(ERR_CLAIM_NOT_WITHDRAWABLE, "Claim has progressed past INJURY_VERIFIED and cannot be withdrawn", 409)

    claim["status"] = "WITHDRAWN"
    bump(claim)
    return success_envelope(claim, 200, "object")
