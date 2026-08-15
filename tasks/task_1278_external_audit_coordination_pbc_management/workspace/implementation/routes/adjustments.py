"""AuditAdjustment endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_ADJUSTMENT_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_ADJUSTMENT_NOT_PROPOSED,
    ERR_RATIONALE_REQUIRED,
    ERR_INVALID_ADJUSTMENT_AMOUNT,
)
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
)

bp = Blueprint("adjustments", __name__)

_VALID_DIRECTIONS = ("DEBIT", "CREDIT")


def _get_adjustment_or_404(adjustment_id):
    a = db.adjustments.get(adjustment_id)
    if a is None:
        raise ApiError(ERR_ADJUSTMENT_NOT_FOUND, "AuditAdjustment id not found", 404)
    return a


@bp.route("/api/adjustments", methods=["POST"])
def create_adjustment():
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    description = body.get("description")
    amount_cents = body.get("amount_cents")
    direction = body.get("direction")

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
    if not isinstance(description, str) or not description.strip():
        raise ApiError("ERR_VALIDATION", "description is required", 400)
    if (
        not isinstance(amount_cents, int)
        or isinstance(amount_cents, bool)
        or amount_cents <= 0
    ):
        raise ApiError(
            ERR_INVALID_ADJUSTMENT_AMOUNT,
            "amount_cents must be > 0",
            400,
        )
    if direction not in _VALID_DIRECTIONS:
        raise ApiError("ERR_VALIDATION", "direction must be DEBIT or CREDIT", 400)

    a = stamp_new(
        {
            "engagement_id": engagement_id,
            "proposed_by_user_id": ctx.user_id,
            "description": description,
            "amount_cents": amount_cents,
            "direction": direction,
            "disposition": "PROPOSED",
            "disposition_rationale": None,
            "disposition_by_user_id": None,
        }
    )
    db.adjustments[a["id"]] = a
    recompute_engagement_derived(eng)
    return success_object(dict(a), 201)


@bp.route("/api/adjustments", methods=["GET"])
def list_adjustments():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    disposition = request.args.get("disposition")
    items = list(db.adjustments.values())
    if engagement_id:
        items = [a for a in items if a["engagement_id"] == engagement_id]
    if disposition:
        items = [a for a in items if a["disposition"] == disposition]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(a) for a in page], limit, offset, total)


@bp.route("/api/adjustments/<adjustment_id>", methods=["GET"])
def get_adjustment(adjustment_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    a = _get_adjustment_or_404(adjustment_id)
    return success_object(dict(a))


@bp.route("/api/adjustments/<adjustment_id>/disposition", methods=["POST"])
def disposition_adjustment(adjustment_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    a = _get_adjustment_or_404(adjustment_id)
    eng = get_engagement_or_404(a["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    # Priority 5: state
    if a["disposition"] != "PROPOSED":
        raise ApiError(
            ERR_ADJUSTMENT_NOT_PROPOSED,
            "Disposition requires AuditAdjustment in PROPOSED",
            409,
        )
    body = request.get_json(force=True, silent=True) or {}
    disposition = body.get("disposition")
    rationale = body.get("rationale")

    if disposition == "ACCEPT":
        a["disposition"] = "ACCEPTED"
        a["disposition_rationale"] = rationale if rationale is not None else None
        a["disposition_by_user_id"] = ctx.user_id
    elif disposition == "REJECT":
        if not isinstance(rationale, str) or not rationale.strip():
            raise ApiError(
                ERR_RATIONALE_REQUIRED,
                "rationale field required when disposition is REJECT or PASS",
                400,
            )
        a["disposition"] = "REJECTED"
        a["disposition_rationale"] = rationale
        a["disposition_by_user_id"] = ctx.user_id
    elif disposition == "PASS":
        if not isinstance(rationale, str) or not rationale.strip():
            raise ApiError(
                ERR_RATIONALE_REQUIRED,
                "rationale field required when disposition is REJECT or PASS",
                400,
            )
        a["disposition"] = "PASSED"
        a["disposition_rationale"] = rationale
        a["disposition_by_user_id"] = ctx.user_id
    else:
        raise ApiError(
            "ERR_VALIDATION", "disposition must be ACCEPT, REJECT, or PASS", 400
        )
    touch(a)
    recompute_engagement_derived(eng)
    return success_object(dict(a))
