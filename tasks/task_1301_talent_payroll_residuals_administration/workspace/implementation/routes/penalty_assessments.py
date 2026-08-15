"""PenaltyAssessment endpoints."""

from flask import Blueprint, request

import db
from calculations import recompute_engagement_accrued_penalty
from errors import ApiError, ERR_RESOURCE_INVALID_STATE, ERR_VALIDATION
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404

bp = Blueprint("penalty_assessments", __name__)


@bp.get("/payroll/penalty-assessments")
def list_penalty_assessments():
    require_roles(ALL_ROLES)
    items = list(db.penalty_assessments.values())
    timecard_id = request.args.get("timecard_id")
    if timecard_id is not None:
        items = [p for p in items if p["timecard_id"] == timecard_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([serialize(p) for p in items], request.args)


@bp.get("/payroll/penalty-assessments/<assessment_id>")
def get_penalty_assessment(assessment_id):
    require_roles(ALL_ROLES)
    assessment = get_or_404(db.penalty_assessments, assessment_id, "PenaltyAssessment")
    return success_object(serialize(assessment), 200)


@bp.post("/payroll/penalty-assessments/<assessment_id>/waive")
def waive_penalty_assessment(assessment_id):
    require_roles({"PayrollSupervisor"})
    assessment = get_or_404(db.penalty_assessments, assessment_id, "PenaltyAssessment")

    if assessment["status"] != "CONFIRMED":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Waive requires status CONFIRMED",
            409,
        )

    body = request.get_json(silent=True)
    waiver_reason = None
    if isinstance(body, dict):
        waiver_reason = body.get("waiver_reason")
    if not isinstance(waiver_reason, str) or waiver_reason == "":
        raise ApiError(ERR_VALIDATION, "waiver_reason is required", 400)

    assessment["status"] = "WAIVED"

    # Compensating recompute on the parent engagement
    timecard = db.timecards.get(assessment["timecard_id"])
    if timecard is not None:
        engagement = db.engagements.get(timecard["engagement_id"])
        if engagement is not None:
            recompute_engagement_accrued_penalty(engagement)

    return success_object(serialize(assessment), 200)
