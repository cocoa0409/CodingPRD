"""Tier assignment endpoint."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CLAIM_INVALID_STATE,
    ERR_NO_PUBLISHED_MATRIX,
    ERR_MATRIX_NOT_PUBLISHED,
    ERR_MATRIX_CATEGORY_MISMATCH,
    ERR_SEVERITY_OUT_OF_RANGE,
    ERR_STALE_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_json_body,
    require_fields,
    resolve_claim,
)
from services.calculations import (
    compute_severity_score,
    tier_assignment as calc_tier_assignment,
    attorney_fee,
    recompute_claim_totals,
)

bp = Blueprint("tier_assignment", __name__)


@bp.route("/settlement-programs/<pid>/claims/<cid>/assign-tier", methods=["POST"])
def assign_tier(pid, cid):
    user_id, role = require_role("ProgramAdministrator")
    prog, claim = resolve_claim(pid, cid)

    body = get_json_body()
    require_fields(body, ["tier_matrix_id", "expected_claim_version"])

    # OCC check BEFORE any state validation
    expected = body["expected_claim_version"]
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_claim_version does not match claim.version", 412)

    # State check
    if claim["status"] != "INJURY_VERIFIED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be INJURY_VERIFIED to assign tier", 409)

    # Program must have at least one PUBLISHED matrix
    has_published = any(
        t for t in db.tier_matrices.values()
        if t["settlement_program_id"] == pid and t["matrix_state"] == "PUBLISHED"
    )
    if not has_published:
        raise ApiError(ERR_NO_PUBLISHED_MATRIX, "Program has no PUBLISHED tier matrix rows", 409)

    # Provided matrix must be PUBLISHED and belong to this program
    tm = db.tier_matrices.get(body["tier_matrix_id"])
    if tm is None or tm["settlement_program_id"] != pid or tm["matrix_state"] != "PUBLISHED":
        raise ApiError(ERR_MATRIX_NOT_PUBLISHED, "Provided tier_matrix_id is not in PUBLISHED state", 409)

    # Category match
    claimant = db.claimants[claim["claimant_id"]]
    if claimant["injury_category"] != tm["injury_category"]:
        raise ApiError(ERR_MATRIX_CATEGORY_MISMATCH, "Claimant injury_category does not match matrix injury_category", 422)

    # Severity range check
    severity = compute_severity_score(cid)
    if severity is None:
        raise ApiError(ERR_SEVERITY_OUT_OF_RANGE, "No ACCEPTED records to compute severity", 422)
    if severity < tm["severity_score_min"] or severity > tm["severity_score_max"]:
        raise ApiError(ERR_SEVERITY_OUT_OF_RANGE, "Severity score %d outside matrix range [%d, %d]" % (severity, tm["severity_score_min"], tm["severity_score_max"]), 422)

    # Run calculations
    claim["gross_award_cents"] = calc_tier_assignment(body["tier_matrix_id"])
    claim["attorney_fee_cents"] = attorney_fee(claim, claimant)
    recompute_claim_totals(claim)

    claim["status"] = "TIER_ASSIGNED"
    claim["lien_posture"] = "IDENTIFYING"
    bump(claim)

    return success_envelope(claim, 200, "object")
