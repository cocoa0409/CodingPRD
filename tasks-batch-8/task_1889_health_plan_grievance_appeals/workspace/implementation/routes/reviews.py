"""ClinicalReview endpoints (PRD section 3.4)."""

from flask import Blueprint, request

import calc
import db
import errors
from auth import require_roles
from envelope import (paginate, parse_pagination, success_list,
                      success_object)
from serializers import review_out
from services import (append_event, get_case_or_404, get_or_404,
                      guard_entity_status, guard_status, live_review_for_case)
from validate import (get_body, opt_number, req_int, req_str)

bp = Blueprint("reviews", __name__)

REVIEW_TERMINAL = ("DETERMINED", "SUPERSEDED")
DETERMINATIONS = {"UPHOLD_SERVICE", "OVERTURN_SERVICE", "PARTIAL"}
VIEW_ROLES = {"PlatformAdmin", "CaseAnalyst", "MedicalDirector",
              "ComplianceOfficer"}

FACTOR_FIELDS = ("severity", "acuity", "guideline_match", "comorbidity",
                 "functional_impairment")


@bp.route("/appeals/cases/<cid>/clinical-reviews", methods=["POST"])
@require_roles({"CaseAnalyst"})
def request_clinical_review(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("IN_REVIEW", "PENDING_CLINICAL"))
    if live_review_for_case(case["id"]) is not None:
        raise errors.review_in_flight()
    review = db.make_common()
    review.update({
        "case_id": case["id"],
        "reviewer_physician_id": None,
        "status": "REQUESTED",
        "determination": None,
        "medical_necessity_score": None,
        "superseded_by_review_id": None,
        "_requested_by": _user_id,
    })
    db.reviews[review["id"]] = review
    if case["status"] == "IN_REVIEW":
        case["status"] = "PENDING_CLINICAL"
    append_event(case, "NOTE", _role, _user_id, body="CLINICAL_REVIEW_REQUESTED")
    db.touch(case)
    return success_object(review_out(review), status=201)


@bp.route("/appeals/clinical-reviews/<rid>", methods=["GET"])
@require_roles(VIEW_ROLES)
def get_review(rid, _user_id, _role):
    return success_object(review_out(get_or_404(db.reviews, rid, "clinical review")))


@bp.route("/appeals/clinical-reviews", methods=["GET"])
@require_roles(VIEW_ROLES)
def list_reviews(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.reviews.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    superseded_by = request.args.get("superseded_by_review_id")
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_review_id"] == superseded_by]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([review_out(r) for r in page], total, limit, offset)


@bp.route("/appeals/clinical-reviews/<rid>/assign", methods=["POST"])
@require_roles({"MedicalDirector"})
def assign_review(rid, _user_id, _role):
    review = get_or_404(db.reviews, rid, "clinical review")
    guard_entity_status(review, ("REQUESTED",), REVIEW_TERMINAL, "clinical review")
    body = get_body()
    reviewer_physician_id = req_str(body, "reviewer_physician_id")
    # Segregation of duties: reviewer must differ from the requesting analyst
    if reviewer_physician_id == review["_requested_by"]:
        raise errors.duty_segregation(
            "reviewer_physician_id must differ from the requesting CaseAnalyst")
    review["reviewer_physician_id"] = reviewer_physician_id
    review["status"] = "ASSIGNED"
    db.touch(review)
    return success_object(review_out(review))


@bp.route("/appeals/clinical-reviews/<rid>/draft-determination", methods=["POST"])
@require_roles({"MedicalDirector"})
def draft_determination(rid, _user_id, _role):
    review = get_or_404(db.reviews, rid, "clinical review")
    guard_entity_status(review, ("ASSIGNED",), REVIEW_TERMINAL, "clinical review")
    if _user_id != review["reviewer_physician_id"]:
        raise errors.duty_segregation(
            "only the assigned reviewer may draft the determination")
    body = get_body()
    factors = {}
    for field in FACTOR_FIELDS:
        value = req_int(body, field)
        if not (0 <= value <= 10):
            raise errors.validation(f"{field} must be between 0 and 10")
        factors[field] = value
    override = opt_number(body, "override_score")
    review["medical_necessity_score"] = calc.medical_necessity_score(
        factors["severity"], factors["acuity"], factors["guideline_match"],
        factors["comorbidity"], factors["functional_impairment"],
        override_score=override)
    review["status"] = "DETERMINATION_DRAFT"
    db.touch(review)
    return success_object(review_out(review))


@bp.route("/appeals/clinical-reviews/<rid>/finalize-determination", methods=["POST"])
@require_roles({"MedicalDirector"})
def finalize_determination(rid, _user_id, _role):
    review = get_or_404(db.reviews, rid, "clinical review")
    guard_entity_status(review, ("DETERMINATION_DRAFT",), REVIEW_TERMINAL,
                        "clinical review")
    if _user_id != review["reviewer_physician_id"]:
        raise errors.duty_segregation(
            "only the assigned reviewer may finalize the determination")
    body = get_body()
    determination = req_str(body, "determination")
    if determination not in DETERMINATIONS:
        raise errors.validation("determination must be one of "
                                "UPHOLD_SERVICE, OVERTURN_SERVICE, PARTIAL")
    review["determination"] = determination
    review["status"] = "DETERMINED"
    db.touch(review)
    return success_object(review_out(review))
