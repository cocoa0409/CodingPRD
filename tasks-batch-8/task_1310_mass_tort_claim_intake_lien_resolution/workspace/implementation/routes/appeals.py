"""Appeal CRUD + adjudication state machine."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_APPEAL_ALREADY_OPEN,
    ERR_APPEAL_INVALID_STATE,
    ERR_MATRIX_NOT_PUBLISHED,
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
    resolve_appeal,
    sort_by_created_at,
)
from services.calculations import (
    tier_assignment,
    attorney_fee,
    recompute_claim_totals,
)

bp = Blueprint("appeals", __name__)

APPEAL_READ_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "LienAnalyst",
    "ClaimantRole",
)


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals", methods=["POST"])
def create_appeal(pid, cid):
    user_id, role = require_role("ClaimantRole")
    prog, claim = resolve_claim(pid, cid)

    # ClaimantRole ownership check
    if user_id != claim["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)

    if claim["status"] != "TIER_ASSIGNED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be TIER_ASSIGNED to file an appeal", 409)

    if claim["active_appeal_id"] is not None:
        raise ApiError(ERR_APPEAL_ALREADY_OPEN, "An appeal is already open on this claim", 409)

    body = get_json_body()
    require_fields(body, ["appealed_tier_matrix_id", "requested_tier_matrix_id", "grounds"])

    grounds = body["grounds"]
    if not isinstance(grounds, str) or len(grounds) < 20:
        raise ApiError(ERR_INVALID_REQUEST, "grounds must be at least 20 characters", 400)

    # Validate requested matrix is PUBLISHED
    requested_tm = db.tier_matrices.get(body["requested_tier_matrix_id"])
    if requested_tm is None or requested_tm["settlement_program_id"] != pid or requested_tm["matrix_state"] != "PUBLISHED":
        raise ApiError(ERR_MATRIX_NOT_PUBLISHED, "Requested tier matrix is not PUBLISHED", 409)

    appeal = {
        "claim_id": cid,
        "appealed_tier_matrix_id": body["appealed_tier_matrix_id"],
        "requested_tier_matrix_id": body["requested_tier_matrix_id"],
        "grounds": grounds,
        "state": "FILED",
        "resolution_rationale": None,
    }
    appeal.update(new_common_fields())
    db.appeals[appeal["id"]] = appeal

    claim["active_appeal_id"] = appeal["id"]
    bump(claim)

    return success_envelope(appeal, 201, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals", methods=["GET"])
def list_appeals(pid, cid):
    user_id, role = require_role(*APPEAL_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)
    limit, offset = get_pagination()

    items = [a for a in db.appeals.values() if a["claim_id"] == cid]

    state_filter = request.args.get("state")
    if state_filter:
        items = [a for a in items if a["state"] == state_filter]

    claim_filter = request.args.get("claim_id")
    if claim_filter:
        items = [a for a in items if a["claim_id"] == claim_filter]

    appealed_filter = request.args.get("appealed_tier_matrix_id")
    if appealed_filter:
        items = [a for a in items if a["appealed_tier_matrix_id"] == appealed_filter]

    requested_filter = request.args.get("requested_tier_matrix_id")
    if requested_filter:
        items = [a for a in items if a["requested_tier_matrix_id"] == requested_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals/<aid>", methods=["GET"])
def get_appeal(pid, cid, aid):
    user_id, role = require_role(*APPEAL_READ_ROLES)
    prog, claim, appeal = resolve_appeal(pid, cid, aid)
    return success_envelope(appeal, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals/<aid>/begin-review", methods=["POST"])
def begin_review(pid, cid, aid):
    user_id, role = require_role("ProgramAdministrator")
    prog, claim, appeal = resolve_appeal(pid, cid, aid)

    if appeal["state"] != "FILED":
        raise ApiError(ERR_APPEAL_INVALID_STATE, "Appeal must be FILED to begin review", 409)

    appeal["state"] = "UNDER_REVIEW"
    bump(appeal)
    return success_envelope(appeal, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals/<aid>/uphold", methods=["POST"])
def uphold_appeal(pid, cid, aid):
    user_id, role = require_role("ProgramAdministrator")
    prog, claim, appeal = resolve_appeal(pid, cid, aid)

    if appeal["state"] != "UNDER_REVIEW":
        raise ApiError(ERR_APPEAL_INVALID_STATE, "Appeal must be UNDER_REVIEW to uphold", 409)

    body = get_json_body()
    require_fields(body, ["resolution_rationale"])
    rationale = body["resolution_rationale"]
    if not isinstance(rationale, str) or len(rationale) < 20:
        raise ApiError(ERR_INVALID_REQUEST, "resolution_rationale must be at least 20 characters", 400)

    # Validate requested matrix is PUBLISHED
    requested_tm = db.tier_matrices.get(appeal["requested_tier_matrix_id"])
    if requested_tm is None or requested_tm["settlement_program_id"] != pid or requested_tm["matrix_state"] != "PUBLISHED":
        raise ApiError(ERR_MATRIX_NOT_PUBLISHED, "Requested tier matrix is not PUBLISHED", 409)

    # Re-run tier assignment with requested matrix
    claimant = db.claimants[claim["claimant_id"]]
    claim["gross_award_cents"] = tier_assignment(appeal["requested_tier_matrix_id"])

    # Re-run attorney fee
    claim["attorney_fee_cents"] = attorney_fee(claim, claimant)

    # Recompute net award (total_lien_cents unchanged)
    claim["net_award_cents"] = max(
        claim["gross_award_cents"] - claim["total_lien_cents"] - claim["attorney_fee_cents"],
        0,
    )

    appeal["state"] = "UPHELD"
    appeal["resolution_rationale"] = rationale
    bump(appeal)

    claim["active_appeal_id"] = None
    bump(claim)

    return success_envelope(appeal, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals/<aid>/deny", methods=["POST"])
def deny_appeal(pid, cid, aid):
    user_id, role = require_role("ProgramAdministrator")
    prog, claim, appeal = resolve_appeal(pid, cid, aid)

    if appeal["state"] != "UNDER_REVIEW":
        raise ApiError(ERR_APPEAL_INVALID_STATE, "Appeal must be UNDER_REVIEW to deny", 409)

    body = get_json_body()
    require_fields(body, ["resolution_rationale"])
    rationale = body["resolution_rationale"]
    if not isinstance(rationale, str) or len(rationale) < 20:
        raise ApiError(ERR_INVALID_REQUEST, "resolution_rationale must be at least 20 characters", 400)

    appeal["state"] = "DENIED"
    appeal["resolution_rationale"] = rationale
    bump(appeal)

    claim["active_appeal_id"] = None
    bump(claim)

    return success_envelope(appeal, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/appeals/<aid>/withdraw", methods=["POST"])
def withdraw_appeal(pid, cid, aid):
    user_id, role = require_role("ClaimantRole")
    prog, claim, appeal = resolve_appeal(pid, cid, aid)

    # ClaimantRole ownership check
    if user_id != claim["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Appeal not found", 404)

    if appeal["state"] != "FILED":
        raise ApiError(ERR_APPEAL_INVALID_STATE, "Appeal must be FILED to withdraw", 409)

    appeal["state"] = "WITHDRAWN"
    bump(appeal)

    claim["active_appeal_id"] = None
    bump(claim)

    return success_envelope(appeal, 200, "object")
