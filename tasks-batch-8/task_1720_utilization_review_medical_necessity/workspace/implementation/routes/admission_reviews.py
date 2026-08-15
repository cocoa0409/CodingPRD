"""AdmissionReview endpoints."""
from flask import Blueprint

import db
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_SOD_ROLE_CONFLICT,
    ERR_TWO_MIDNIGHT_DOC_REQUIRED,
)
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.calculations import medical_necessity_score, MET_THRESHOLD
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int, validate_bool,
    validate_string,
)

bp = Blueprint("admission_reviews", __name__)

CRITERIA_SETS = {"INTERQUAL", "MCG"}
ADVISOR_DECISIONS = {"REVERSE", "UPHOLD"}

CREATE_FIELDS = [
    "criteria_set", "severity_of_illness_points", "intensity_of_service_points",
    "comorbidity_count", "two_midnight_attestation",
]


def _compute_determination_and_recommendation(case, review):
    score = medical_necessity_score(
        review["severity_of_illness_points"],
        review["intensity_of_service_points"],
        review["comorbidity_count"],
        db.payers[case["payer_id"]]["plan_class"],
    )
    determination = "CRITERIA_MET" if score >= MET_THRESHOLD else "CRITERIA_NOT_MET"
    if determination == "CRITERIA_MET" and case["two_midnight_benchmark_met"] == "MET":
        recommended = "INPATIENT"
    else:
        recommended = "OBSERVATION"
    return score, determination, recommended


@bp.post("/api/utilization-cases/<cid>/admission-reviews")
def create_admission_review(cid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_enum(body, "criteria_set", CRITERIA_SETS)
    validate_int(body, "severity_of_illness_points", min_val=0, max_val=20)
    validate_int(body, "intensity_of_service_points", min_val=0, max_val=20)
    validate_int(body, "comorbidity_count", min_val=0, max_val=10)
    validate_bool(body, "two_midnight_attestation")

    case = lookup(db.utilization_cases, cid, "UtilizationCase")
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)

    review = {
        **init_common(),
        "case_id": cid,
        "criteria_set": body["criteria_set"],
        "severity_of_illness_points": body["severity_of_illness_points"],
        "intensity_of_service_points": body["intensity_of_service_points"],
        "comorbidity_count": body["comorbidity_count"],
        "two_midnight_attestation": body["two_midnight_attestation"],
        "necessity_score": None,
        "determination": "PENDING",
        "recommended_status": None,
        "status": "DRAFT",
        "submitted_at": None,
    }
    db.admission_reviews[review["id"]] = review
    return success_object(review, 201)


@bp.get("/api/utilization-cases/<cid>/admission-reviews")
def list_admission_reviews(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (r for r in db.admission_reviews.values() if r["case_id"] == cid),
        key=lambda r: r["created_at"],
    )
    return paginate(items)


@bp.get("/api/admission-reviews/<rid>")
def get_admission_review(rid):
    any_authenticated()
    return success_object(lookup(db.admission_reviews, rid, "AdmissionReview"))


@bp.post("/api/admission-reviews/<rid>/submit")
def submit_admission_review(rid):
    user_id, role = require_roles(["URNurse"])
    get_json_body()  # tolerate empty body

    review = lookup(db.admission_reviews, rid, "AdmissionReview")
    case = db.utilization_cases[review["case_id"]]

    # Case-open gate (priority 6)
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # State legality (priority 7)
    if review["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Review is not in DRAFT", 409)

    score, determination, recommended = _compute_determination_and_recommendation(case, review)

    # Two-midnight documentation gate (priority 14)
    if recommended == "INPATIENT" and not review["two_midnight_attestation"]:
        raise ApiError(
            ERR_TWO_MIDNIGHT_DOC_REQUIRED,
            "Review recommends INPATIENT but two_midnight_attestation is false",
            422,
        )

    from db import now_iso
    review["necessity_score"] = score
    review["determination"] = determination
    review["recommended_status"] = recommended
    review["status"] = "SUBMITTED"
    review["submitted_at"] = now_iso()
    touch(review)

    if case["review_status"] == "INTAKE":
        case["review_status"] = "ADMISSION_REVIEWED"
    touch(case)
    append_audit(case["id"], "REVIEW_SUBMITTED", role, user_id,
                 f"Admission review {rid} submitted; determination={determination}, score={score}")
    return success_object(review, 200)


@bp.post("/api/admission-reviews/<rid>/advisor-review")
def advisor_review(rid):
    user_id, role = require_roles(["PhysicianAdvisor"])
    body = get_json_body()
    reject_unknown_fields(body, ["advisor_decision", "advisor_note"])
    validate_enum(body, "advisor_decision", ADVISOR_DECISIONS)
    validate_string(body, "advisor_note", required=False)

    review = lookup(db.admission_reviews, rid, "AdmissionReview")
    case = db.utilization_cases[review["case_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if review["status"] != "SUBMITTED" or review["determination"] != "CRITERIA_NOT_MET":
        raise ApiError(ERR_INVALID_STATE,
                       "Advisor review requires SUBMITTED status and CRITERIA_NOT_MET determination",
                       409)
    # Segregation of duties (priority 13)
    if user_id == case["attending_physician_id"]:
        raise ApiError(ERR_SOD_ROLE_CONFLICT,
                       "Advisor reviewer must differ from the case attending physician",
                       422)

    if body["advisor_decision"] == "REVERSE":
        review["determination"] = "CRITERIA_MET"
        if case["two_midnight_benchmark_met"] == "MET":
            review["recommended_status"] = "INPATIENT"
        else:
            review["recommended_status"] = "OBSERVATION"
    review["status"] = "ADVISOR_REVIEWED"
    touch(review)
    append_audit(case["id"], "ADVISOR_REVIEW_COMPLETED", role, user_id,
                 f"Advisor review of {rid}: {body['advisor_decision']}")
    return success_object(review, 200)
