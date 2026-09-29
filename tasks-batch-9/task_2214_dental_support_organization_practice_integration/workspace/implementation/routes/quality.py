"""Clinical quality reviews: the corporate-practice boundary on oversight (PRD 3.8)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError, invalid
from services import calc, uow

bp = Blueprint("quality", __name__)


def _stamp_score(review):
    result = calc.clinical_quality_score(
        review["charts_sampled"],
        review["charts_with_findings"],
        review["treatment_plan_overrides"],
    )
    review["finding_rate_bps"] = result["finding_rate_bps"]
    review["override_rate_bps"] = result["override_rate_bps"]
    review["score_bps"] = result["score_bps"]


@bp.post("/clinical-quality-reviews")
@support.transactional
def create_review():
    middleware.authorize([config.ROLE_CLINICAL_DIRECTOR], clinician_identity=True)
    data = payload.body()
    employment = support.load_fk(data, "doctor_employment_id", "doctor_employments")
    payload.string(data, "doctor_employment_id")
    period_label = payload.string(data, "period_label")
    # No payload-level floor: the sample-size rule is priority 39 (422), not 400.
    charts_sampled = payload.integer(data, "charts_sampled")
    charts_with_findings = payload.integer(data, "charts_with_findings", minimum=0)
    treatment_plan_overrides = payload.integer(
        data, "treatment_plan_overrides", minimum=0
    )
    if charts_with_findings > charts_sampled:
        raise invalid("'charts_with_findings' may not exceed 'charts_sampled'.")
    if treatment_plan_overrides > charts_sampled:
        raise invalid("'treatment_plan_overrides' may not exceed 'charts_sampled'.")

    if employment["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_EMPLOYMENT_STATE",
            "Only an ACTIVE employment can be reviewed.",
        )
    if charts_sampled < config.MIN_CHARTS_SAMPLED:
        raise ApiError(
            "ERR_SAMPLE_SIZE_TOO_SMALL",
            "At least %d charts must be sampled." % config.MIN_CHARTS_SAMPLED,
        )

    row = db.insert(
        "clinical_quality_reviews",
        {
            "doctor_employment_id": employment["id"],
            "period_label": period_label,
            "charts_sampled": charts_sampled,
            "charts_with_findings": charts_with_findings,
            "treatment_plan_overrides": treatment_plan_overrides,
            "status": "OPEN",
            "finding_rate_bps": None,
            "override_rate_bps": None,
            "score_bps": None,
            "closed_by_doctor_id": None,
            "outcome_note": None,
        },
    )
    _stamp_score(row)
    return "clinical_quality_reviews", row, 201


@bp.get("/clinical-quality-reviews/<clinical_quality_review_id>")
def get_review(clinical_quality_review_id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_CLINICAL_DIRECTOR,
            config.ROLE_DENTIST,
        ]
    )
    row = support.load("clinical_quality_reviews", clinical_quality_review_id)
    return support.read_one("clinical_quality_reviews", row)


@bp.post("/clinical-quality-reviews/<clinical_quality_review_id>/close")
@support.transactional
def close_review(clinical_quality_review_id):
    user_id, _ = middleware.authorize(
        [config.ROLE_CLINICAL_DIRECTOR], clinician_identity=True
    )
    review = support.load("clinical_quality_reviews", clinical_quality_review_id)
    data = payload.body()
    outcome = payload.enum(data, "outcome", config.QUALITY_OUTCOMES)
    outcome_note = payload.string(data, "outcome_note", required=False)

    if review["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_WORKFLOW_STATE", "Only an open review can be closed."
        )

    employment = db.get("doctor_employments", review["doctor_employment_id"])
    practice = db.get("practices", employment["practice_id"])
    director = db.get("doctors", user_id)
    if director["license_state"] != practice["state_code"]:
        raise ApiError(
            "ERR_CORPORATE_PRACTICE_VIOLATION",
            "Clinical oversight requires a director licensed in the practice's state.",
        )
    if director["id"] == employment["doctor_id"]:
        raise ApiError(
            "ERR_SELF_REVIEW_PROHIBITED",
            "A clinician cannot close the review of their own charts.",
        )

    # The score is re-stamped from the stored sample before the coupling gate,
    # so the outcome is always judged against the current formula.
    _stamp_score(review)
    score = review["score_bps"]
    if outcome == "CLOSED_NO_FINDINGS" and score != config.FULL_SCORE_BPS:
        raise ApiError(
            "ERR_QUALITY_OUTCOME_MISMATCH",
            "A no-findings close requires a perfect score.",
        )
    if (
        outcome == "CLOSED_WITH_PLAN"
        and score < config.QUALITY_ESCALATION_THRESHOLD_BPS
    ):
        raise ApiError(
            "ERR_QUALITY_OUTCOME_MISMATCH",
            "A score below the escalation threshold must escalate.",
        )

    review["status"] = outcome
    review["closed_by_doctor_id"] = user_id
    review["outcome_note"] = outcome_note
    uow.touch(review)
    return "clinical_quality_reviews", review, 200
