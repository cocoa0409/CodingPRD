"""Loss determination endpoints (PRD 3.8): the UNDER_REVIEW → APPROVED/DENIED
decision with the final-indemnity waterfall and the reserve/claim-count cascade."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
    ERR_CLAIM_NOT_IN_UNDER_REVIEW, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_DOCS_INCOMPLETE, ERR_INDEMNITY_EXCEEDS_RESERVE,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy, resolve_claim
from serializers import determination_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_enum, require_int,
    parse_pagination, paginate, sort_created,
)

bp = Blueprint("determinations", __name__)

LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {
    "decision", "approved_indemnity_cents", "denial_reason_code",
    "expected_policy_version",
}
DENIAL_REASONS = {
    "FRAUD", "NOT_COVERED_PERIL", "LATE_NOTICE_OVER_30D", "MISSING_DOCS",
    "POLICY_INACTIVE",
}


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/determinations",
          methods=["POST"])
@require_roles("ClaimsApprover")
def create_determination(carrierId: str, policyId: str, claimId: str,
                         _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    decision = require_enum(body, "decision", {"APPROVE", "DENY", "PARTIAL"})
    approved_cents = require_int(body, "approved_indemnity_cents", minimum=0)
    denial_reason = None
    if "denial_reason_code" in body and body["denial_reason_code"] is not None:
        denial_reason = require_enum(body, "denial_reason_code", DENIAL_REASONS)
    expected_version = require_int(body, "expected_policy_version", minimum=0)

    if decision == "DENY":
        if denial_reason is None:
            raise_err(ERR_INVALID_REQUEST,
                      "denial_reason_code is required when decision is DENY")
        if approved_cents != 0:
            raise_err(ERR_INVALID_REQUEST,
                      "approved_indemnity_cents must be 0 when decision is DENY")

    # OCC (pipeline priority 3.5): ahead of state and every business rule.
    if expected_version != policy["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_policy_version does not match the policy's current version")

    # State guard.
    if claim["claim_state"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_NOT_IN_UNDER_REVIEW,
                  "determinations require claim_state UNDER_REVIEW")

    # Segregation of duties: the inspecting adjuster can never approve.
    if _user_id == claim["adjuster_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The assigned adjuster cannot issue the loss determination")

    # Livestock documentation gate.
    if claim["claim_kind"] == "LIVESTOCK_MORTALITY" and decision in ("APPROVE", "PARTIAL"):
        if claim["doc_posture"] not in ("DOCS_COMPLETE", "DOCS_WAIVED"):
            raise_err(ERR_DOCS_INCOMPLETE,
                      "Livestock claim requires DOCS_COMPLETE or DOCS_WAIVED to approve")

    # Effective base: straight approval pays the provisional; PARTIAL uses the
    # approver-supplied figure; DENY pays nothing.
    if decision == "APPROVE":
        base = claim["provisional_indemnity_cents"]
    elif decision == "PARTIAL":
        base = approved_cents
    else:
        base = 0

    # Fiscal guard (runs last): cap at reserve + provisional.
    if base > policy["premium_reserve_cents"] + claim["provisional_indemnity_cents"]:
        raise_err(ERR_INDEMNITY_EXCEEDS_RESERVE,
                  "approved_indemnity_cents exceeds premium_reserve + provisional")

    now = carrier["current_utc"]
    unit = db.coverage_units.get(claim["coverage_unit_id"])
    coverage_pct, late_pct, offset, final = core.final_indemnity_waterfall(
        policy, claim, unit, base)

    determination = db.stamp_new({
        "claim_id": claim["id"],
        "reviewer_id": _user_id,
        "decision": decision,
        "approved_indemnity_cents": base,
        "applied_coverage_reduction_pct": coverage_pct,
        "applied_late_notification_penalty_pct": late_pct,
        "applied_dual_coverage_offset_cents": offset,
        "final_indemnity_cents": final,
        "denial_reason_code": denial_reason if decision == "DENY" else None,
        "decided_at": now,
    }, now)
    db.determinations[determination["id"]] = determination

    if decision in ("APPROVE", "PARTIAL"):
        claim["claim_state"] = "APPROVED"
        claim["final_indemnity_cents"] = final
        db.touch(claim, now)
        core.settle_unit_for_decision(claim, now)
        grower = db.growers.get(policy["grower_id"])
        if grower is not None:
            grower["prior_claims_count"] += 1
            db.touch(grower, now)
        core.recompute_reserve(policy)
        db.touch(policy, now)  # cascade bumps the OCC target (PRD 2.4/2.8)
    else:
        claim["claim_state"] = "DENIED"
        db.touch(claim, now)
        core.settle_unit_for_decision(claim, now)
        db.touch(policy, now)

    return success_object(determination_view(determination), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/determinations",
          methods=["GET"])
@require_roles(*LIST_ROLES)
def list_determinations(carrierId: str, policyId: str, claimId: str,
                        _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    items = [d for d in db.determinations.values() if d["claim_id"] == claim["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([determination_view(d) for d in page], limit, offset, total)
