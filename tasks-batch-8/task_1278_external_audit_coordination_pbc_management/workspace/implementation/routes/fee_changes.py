"""FeeChangeRequest endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_FEE_CHANGE_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_FEE_CHANGE_NOT_PROPOSED,
    ERR_FEE_CHANGE_SELF_APPROVAL,
    ERR_FEE_CHANGE_NOT_PROPOSER,
    ERR_FEE_WOULD_GO_NONPOSITIVE,
    ERR_INVALID_FEE_DELTA,
)
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
)

bp = Blueprint("fee_changes", __name__)


def _get_fee_change_or_404(fee_change_id):
    f = db.fee_change_requests.get(fee_change_id)
    if f is None:
        raise ApiError(
            ERR_FEE_CHANGE_NOT_FOUND, "FeeChangeRequest id not found", 404
        )
    return f


@bp.route("/api/fee-change-requests", methods=["POST"])
def create_fee_change():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    scope_description = body.get("scope_description")
    delta_cents = body.get("delta_cents")

    if not isinstance(engagement_id, str) or not engagement_id.strip():
        raise ApiError("ERR_VALIDATION", "engagement_id is required", 400)
    eng = get_engagement_or_404(engagement_id)
    recompute_engagement_derived(eng)
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    if not isinstance(scope_description, str) or not scope_description.strip():
        raise ApiError("ERR_VALIDATION", "scope_description is required", 400)
    if (
        not isinstance(delta_cents, int)
        or isinstance(delta_cents, bool)
        or delta_cents == 0
    ):
        raise ApiError(
            ERR_INVALID_FEE_DELTA, "delta_cents must be non-zero", 400
        )

    proposed_by_role = "CONTROLLER_OFFICE" if ctx.role == "Controller" else "AUDITOR"
    f = stamp_new(
        {
            "engagement_id": engagement_id,
            "proposed_by_role": proposed_by_role,
            "scope_description": scope_description,
            "delta_cents": delta_cents,
            "status": "PROPOSED",
        }
    )
    db.fee_change_requests[f["id"]] = f
    recompute_engagement_derived(eng)
    return success_object(dict(f), 201)


@bp.route("/api/fee-change-requests", methods=["GET"])
def list_fee_changes():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    items = list(db.fee_change_requests.values())
    if engagement_id:
        items = [f for f in items if f["engagement_id"] == engagement_id]
    if status:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(f) for f in page], limit, offset, total)


@bp.route("/api/fee-change-requests/<fee_change_id>", methods=["GET"])
def get_fee_change(fee_change_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    f = _get_fee_change_or_404(fee_change_id)
    return success_object(dict(f))


@bp.route("/api/fee-change-requests/<fee_change_id>/resolve", methods=["POST"])
def resolve_fee_change(fee_change_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "ExternalAuditor"])
    f = _get_fee_change_or_404(fee_change_id)
    eng = get_engagement_or_404(f["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 5: state
    if f["status"] != "PROPOSED":
        raise ApiError(
            ERR_FEE_CHANGE_NOT_PROPOSED,
            "Resolve requires FeeChangeRequest in PROPOSED",
            409,
        )
    # Priority 7: counter-party approval
    expected_role = (
        "ExternalAuditor" if f["proposed_by_role"] == "CONTROLLER_OFFICE" else "Controller"
    )
    if ctx.role != expected_role:
        raise ApiError(
            ERR_FEE_CHANGE_SELF_APPROVAL,
            "FeeChangeRequest must be resolved by the counter-party, not the proposer",
            403,
        )
    body = request.get_json(force=True, silent=True) or {}
    decision = body.get("decision")
    if decision == "APPROVE":
        # Priority 13: fee floor
        if eng["total_fee_cents"] + f["delta_cents"] <= 0:
            raise ApiError(
                ERR_FEE_WOULD_GO_NONPOSITIVE,
                "Resolution would push total_fee_cents <= 0",
                402,
            )
        f["status"] = "APPROVED"
        touch(f)
        recompute_engagement_derived(eng)
    elif decision == "REJECT":
        f["status"] = "REJECTED"
        touch(f)
        recompute_engagement_derived(eng)
    else:
        raise ApiError("ERR_VALIDATION", "decision must be APPROVE or REJECT", 400)
    return success_object(dict(f))


@bp.route("/api/fee-change-requests/<fee_change_id>/withdraw", methods=["POST"])
def withdraw_fee_change(fee_change_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "ExternalAuditor"])
    f = _get_fee_change_or_404(fee_change_id)
    # Priority 5: state
    if f["status"] != "PROPOSED":
        raise ApiError(
            ERR_FEE_CHANGE_NOT_PROPOSED,
            "Withdraw requires FeeChangeRequest in PROPOSED",
            409,
        )
    # Proposer match
    expected_role = (
        "Controller" if f["proposed_by_role"] == "CONTROLLER_OFFICE" else "ExternalAuditor"
    )
    if ctx.role != expected_role:
        raise ApiError(
            ERR_FEE_CHANGE_NOT_PROPOSER,
            "Withdraw must be performed by the same role that proposed the FeeChangeRequest",
            403,
        )
    f["status"] = "WITHDRAWN"
    touch(f)
    eng = db.engagements.get(f["engagement_id"])
    if eng:
        recompute_engagement_derived(eng)
    return success_object(dict(f))
