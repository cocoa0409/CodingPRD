"""ManagementAdjustment endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ADJUSTMENT_EXCEEDS_CAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_ZERO_ADJUSTMENT,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import (
    CAP_PERCENT,
    get_or_404,
    public,
    resync_run_totals,
    round_half_up_int,
    stamp_new,
    touch,
)
from validation import get_body, paginate, parse_pagination, req_int, req_str, sorted_by_creation

bp = Blueprint("adjustments", __name__)


@bp.post("/cecl/model-runs/<runId>/management-adjustments")
def create_adjustment(runId):
    user_id, _ = require_roles(["CreditAnalyst"])
    run = get_or_404(db.runs, runId, "ModelRun")
    body = get_body()
    amount = req_int(body, "amount_cents")
    rationale = req_str(body, "rationale")
    expected_version = req_int(body, "expected_model_run_version")
    if not rationale.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "rationale must be non-empty")
    if run["status"] not in ("EXECUTED", "UNDER_REVIEW"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Adjustments can only be proposed while the run is EXECUTED or UNDER_REVIEW",
        )
    if expected_version != run["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_model_run_version does not equal the run's current version",
        )
    if amount == 0:
        raise ApiError(ERR_ZERO_ADJUSTMENT, 422, "amount_cents must not be zero")
    subtotal = (
        run["quantitative_reserve_cents"]
        + run["qualitative_adjustment_cents"]
        + run["individual_reserve_cents"]
    )
    cap = round_half_up_int(Decimal(subtotal) * CAP_PERCENT)
    if abs(amount) > cap:
        raise ApiError(
            ERR_ADJUSTMENT_EXCEEDS_CAP,
            422,
            "|amount_cents| exceeds the 10% cap of the run subtotal",
        )
    adjustment = stamp_new(
        {
            "run_id": run["id"],
            "amount_cents": amount,
            "rationale": rationale,
            "status": "PENDING",
            "created_by_user_id": user_id,
            "resolved_by_user_id": None,
        }
    )
    db.adjustments[adjustment["id"]] = adjustment
    # The proposal mutates the run: bump its version
    touch(run)
    return success_response(public(adjustment), 201)


@bp.get("/cecl/model-runs/<runId>/management-adjustments")
def list_adjustments(runId):
    require_roles(ALL_ROLES)
    get_or_404(db.runs, runId, "ModelRun")
    limit, offset = parse_pagination()
    items = [a for a in db.adjustments.values() if a["run_id"] == runId]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(a) for a in page], 200, "array", pagination)


@bp.post("/cecl/management-adjustments/<adjustmentId>/approve")
def approve_adjustment(adjustmentId):
    user_id, _ = require_roles(["ChiefCreditOfficer"])
    get_body()
    adjustment = get_or_404(db.adjustments, adjustmentId, "ManagementAdjustment")
    if adjustment["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a PENDING adjustment can be approved",
        )
    run = db.runs[adjustment["run_id"]]
    if run["status"] not in ("EXECUTED", "UNDER_REVIEW"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "The parent run must be EXECUTED or UNDER_REVIEW to approve an adjustment",
        )
    if user_id == adjustment["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            409,
            "The approver must differ from the adjustment's creator",
        )
    adjustment["status"] = "APPROVED"
    adjustment["resolved_by_user_id"] = user_id
    touch(adjustment)
    resync_run_totals(run)
    touch(run)
    return success_response(public(adjustment), 200)


@bp.post("/cecl/management-adjustments/<adjustmentId>/reject")
def reject_adjustment(adjustmentId):
    user_id, _ = require_roles(["ChiefCreditOfficer"])
    get_body()
    adjustment = get_or_404(db.adjustments, adjustmentId, "ManagementAdjustment")
    if adjustment["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a PENDING adjustment can be rejected",
        )
    run = db.runs[adjustment["run_id"]]
    if run["status"] not in ("EXECUTED", "UNDER_REVIEW", "APPROVED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "The parent run must be EXECUTED, UNDER_REVIEW, or APPROVED to reject an adjustment",
        )
    adjustment["status"] = "REJECTED"
    adjustment["resolved_by_user_id"] = user_id
    touch(adjustment)
    return success_response(public(adjustment), 200)
