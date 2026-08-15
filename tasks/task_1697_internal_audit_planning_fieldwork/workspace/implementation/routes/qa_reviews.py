"""QAReview endpoints (PRD 3.9): scheduling, independence-gated begin,
assessor-owned completion, and the FAIL regression cascade."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_NOT_QA_ASSESSOR,
    ERR_QA_ASSESSOR_ASSIGNED,
    ERR_QA_REVIEW_ALREADY_OPEN,
    ERR_QA_REVIEW_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import compute_qa_overall
from services.cascades import qa_fail_cascade
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    body_ref,
    check_score_range,
    check_unknown_fields,
    get_body,
    req_enum,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("qa_reviews", __name__)

CREATE_FIELDS = {"engagement_id", "scope"}
COMPLETE_FIELDS = {
    "doc_quality_score", "fieldwork_quality_score",
    "reporting_quality_score", "independence_score",
}
SCOPES = ("INTERNAL", "EXTERNAL")


@bp.post("/audit/qa-reviews")
def create_qa_review():
    authorized(["ChiefAuditExecutive"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "engagement_id", "engagements")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    engagement_id = req_str(body, "engagement_id")
    scope = req_enum(body, "scope", SCOPES)
    eng = db["engagements"][engagement_id]
    # Stage 7: engagement must be in REPORTING or CLOSED
    if eng["status"] not in ("REPORTING", "CLOSED"):
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"QA scheduling requires REPORTING or CLOSED, not {eng['status']}")
    # Stage 9: at most one open review per engagement
    for q in db["qa_reviews"].values():
        if q["engagement_id"] == engagement_id and q["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise_error(ERR_QA_REVIEW_ALREADY_OPEN,
                        "a QA review is already SCHEDULED or IN_PROGRESS for this engagement")
    rec = new_record("qa_reviews", {
        "engagement_id": engagement_id,
        "scope": scope,
        "assessor_auditor_id": None,
        "doc_quality_score": None,
        "fieldwork_quality_score": None,
        "reporting_quality_score": None,
        "independence_score": None,
        "overall_score": None,
        "rating": None,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/qa-reviews")
def list_qa_reviews():
    filters = {
        "engagement_id": query_str("engagement_id"),
        "assessor_auditor_id": query_str("assessor_auditor_id"),
        "status": query_str("status"),
    }
    return list_response("qa_reviews", filters)


@bp.get("/audit/qa-reviews/<rid>")
def get_qa_review(rid):
    return get_one("qa_reviews", rid)


@bp.post("/audit/qa-reviews/<rid>/begin")
def begin_qa_review(rid):
    caller = authorized(["QualityAssessor"])
    qa = require_path("qa_reviews", rid)
    # Stage 7: must be SCHEDULED
    if qa["status"] != "SCHEDULED":
        raise_error(ERR_QA_REVIEW_INVALID_STATE, "QA review is not SCHEDULED")
    # Stage 8: independence — the assessor holds no ACTIVE assignment on the
    # engagement under review
    for a in db["engagement_assignments"].values():
        if (a["engagement_id"] == qa["engagement_id"]
                and a["auditor_id"] == caller.user_id
                and a["status"] == "ACTIVE"):
            raise_error(ERR_QA_ASSESSOR_ASSIGNED,
                        "assessor holds an ACTIVE assignment on the reviewed engagement")
    qa["status"] = "IN_PROGRESS"
    qa["assessor_auditor_id"] = caller.user_id
    touch(qa)
    return success_object(public(qa))


@bp.post("/audit/qa-reviews/<rid>/complete")
def complete_qa_review(rid):
    caller = authorized(["QualityAssessor"])
    qa = require_path("qa_reviews", rid)
    # Stage 5: shape — four dimension scores, each a well-typed integer in 1..5
    body = get_body()
    check_unknown_fields(body, COMPLETE_FIELDS)
    doc = req_int(body, "doc_quality_score")
    fieldwork = req_int(body, "fieldwork_quality_score")
    reporting = req_int(body, "reporting_quality_score")
    independence = req_int(body, "independence_score")
    check_score_range(doc, "doc_quality_score")
    check_score_range(fieldwork, "fieldwork_quality_score")
    check_score_range(reporting, "reporting_quality_score")
    check_score_range(independence, "independence_score")
    # Stage 7: must be IN_PROGRESS
    if qa["status"] != "IN_PROGRESS":
        raise_error(ERR_QA_REVIEW_INVALID_STATE, "QA review is not IN_PROGRESS")
    # Stage 8: ownership — only the assigned assessor may complete
    if caller.user_id != qa["assessor_auditor_id"]:
        raise_error(ERR_NOT_QA_ASSESSOR, "only the assigned assessor may complete the review")
    overall, rating = compute_qa_overall(doc, fieldwork, reporting, independence)
    qa["doc_quality_score"] = doc
    qa["fieldwork_quality_score"] = fieldwork
    qa["reporting_quality_score"] = reporting
    qa["independence_score"] = independence
    qa["overall_score"] = overall
    qa["rating"] = rating
    qa["status"] = "COMPLETED"
    qa["completed_at"] = CLOCK.now_iso()
    touch(qa)
    # FAIL while the engagement is still REPORTING triggers the regression
    # cascade; a FAIL against a CLOSED engagement changes nothing downstream.
    eng = db["engagements"].get(qa["engagement_id"])
    if rating == "FAIL" and eng is not None and eng["status"] == "REPORTING":
        qa_fail_cascade(eng)
    return success_object(public(qa))
