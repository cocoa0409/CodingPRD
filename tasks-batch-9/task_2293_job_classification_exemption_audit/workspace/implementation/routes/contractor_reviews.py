"""Independent-contractor review (PRD 3.9)."""
from flask import Blueprint

import db
from constants import ECONOMIC_REALITY_KEYS
from errors import fail
from middleware import body, endpoint
from response import success
from services import calculations, derive, lookup, serialize
from validation import opt_bool, opt_int, opt_obj, req_str

bp = Blueprint("contractor_reviews", __name__)

FINALIZED_BY_OUTCOME = {
    "CONTRACTOR": "FINALIZED_CONTRACTOR",
    "EMPLOYEE": "FINALIZED_EMPLOYEE",
    "INDETERMINATE": "FINALIZED_INDETERMINATE",
}


@bp.post("/contractor-reviews")
@endpoint(["ComplianceAnalyst"])
def create_review():
    payload = body()
    project_id = req_str(payload, "audit_project_id")
    vendor_name = req_str(payload, "vendor_name")
    engagement_state_code = req_str(payload, "engagement_state_code")
    free_from_control = opt_bool(payload, "free_from_control", default=None)
    outside_usual_course = opt_bool(payload, "outside_usual_course", default=None)
    independent_trade = opt_bool(payload, "independent_trade", default=None)
    factors = opt_obj(payload, "economic_reality_factors", default=None)
    behavioral = opt_int(payload, "behavioral_control_score", minimum=0, maximum=5)
    financial = opt_int(payload, "financial_control_score", minimum=0, maximum=5)
    relationship = opt_int(payload, "relationship_score", minimum=0, maximum=5)

    if factors is not None:
        for key, value in factors.items():
            if not isinstance(value, bool):
                fail(
                    "ERR_INVALID_REQUEST",
                    "economic_reality_factors.%s must be a boolean." % key,
                )

    # rank 5: foreign key
    project = lookup.project(project_id)

    # rank 6: engagement posture
    if derive.remediation_posture(project) == "FROZEN":
        fail("ERR_PROJECT_POSTURE_FROZEN")

    draft = {
        "free_from_control": free_from_control,
        "outside_usual_course": outside_usual_course,
        "independent_trade": independent_trade,
        "economic_reality_factors": factors,
        "behavioral_control_score": behavioral,
        "financial_control_score": financial,
        "relationship_score": relationship,
    }
    applied_ic_test = calculations.ic_test_for_state(engagement_state_code)

    # rank 13: the applicable test's inputs must all be supplied
    if not calculations.contractor_required_inputs_present(draft, applied_ic_test):
        fail("ERR_IC_TEST_INPUTS_MISSING")

    computed = calculations.contractor_classification(draft, applied_ic_test)
    row = db.make_row(
        audit_project_id=project["id"],
        vendor_name=vendor_name,
        engagement_state_code=engagement_state_code,
        applied_ic_test=applied_ic_test,
        ic_score=computed["ic_score"],
        outcome=computed["outcome"],
        status="DRAFT",
        **draft
    )
    db.contractor_reviews[row["id"]] = row
    return success(serialize.contractor_review(row), 201)


@bp.post("/contractor-reviews/<review_id>/finalize")
@endpoint(["ClassificationReviewer"])
def finalize_review(review_id):
    review = lookup.contractor_review(review_id)

    # rank 8: the three finalized states are terminal
    if review["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    target = FINALIZED_BY_OUTCOME.get(review["outcome"])
    if target is None:
        fail("ERR_INVALID_STATE_TRANSITION")

    review["status"] = target
    db.touch(review)

    # only the employee branch touches the engagement
    if target == "FINALIZED_EMPLOYEE":
        project = db.audit_projects.get(review["audit_project_id"])
        if project is not None:
            db.touch(project)
    return success(serialize.contractor_review(review), 200)
