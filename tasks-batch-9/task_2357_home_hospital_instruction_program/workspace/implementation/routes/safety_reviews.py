"""Home-visit safety review and the virtual alternative (PRD §3.5)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import CLEARANCE_BANDS, EVIDENCE_SOURCES, HAZARD_CODES, REVIEW_STATUSES, listing
from services import logic
from validation import parse_date

bp = Blueprint("safety_reviews", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "HomeboundTeacher"]

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "evidence_source": {"type": "string", "required": True, "enum": EVIDENCE_SOURCES},
    "review_date": {"type": "date", "required": True},
    "hazard_findings": {"type": "array", "items_enum": HAZARD_CODES, "distinct": True},
    "escort_available": {"type": "boolean"},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "status": {"type": "string", "enum": REVIEW_STATUSES},
    "clearance": {"type": "string", "enum": CLEARANCE_BANDS},
}


@bp.post("/hhi/safety-reviews")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_review():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                      # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    review_date = parse_date(body["review_date"])
    row = {
        "case_id": case["id"],
        "evidence_source": body["evidence_source"],
        "hazard_findings": body.get("hazard_findings", []),
        "escort_available": body.get("escort_available", False),
        "review_date": body["review_date"],
        "expires_on": (
            review_date + timedelta(days=logic.SAFETY_REVIEW_VALIDITY_DAYS)
        ).isoformat(),
        "scoring_variant": (
            "SELF_REPORTED"
            if body["evidence_source"] == "PARENT_ATTESTATION"
            else "ONSITE_VERIFIED"
        ),
        "risk_score": 0,
        "clearance": "PENDING",
        "status": "DRAFT",
        "finalized_by_user_id": None,
    }
    row["risk_score"] = logic.risk_score(row)
    return middleware.obj(db.insert("safety_reviews", row))


@bp.get("/hhi/safety-reviews/<review_id>")
@endpoint(READ_ROLES)
def read_review(review_id):
    row = db.get("safety_reviews", review_id)
    if row is None:
        raise ApiError("ERR_SAFETY_REVIEW_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/safety-reviews")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_reviews():
    return listing("safety_reviews", LIST_QUERY)


@bp.post("/hhi/safety-reviews/<review_id>/finalize")
@endpoint(["CaseManager"])
def finalize_review(review_id):
    review = db.get("safety_reviews", review_id)
    if review is None:
        raise ApiError("ERR_SAFETY_REVIEW_NOT_FOUND")
    if review["status"] != "DRAFT":                               # tier 8
        raise ApiError("ERR_REVIEW_ALREADY_FINALIZED")

    case = db.get("cases", review["case_id"])
    score = logic.risk_score(review)
    clearance = logic.band_clearance(score)
    forces_virtual = clearance == "VIRTUAL_ONLY" and case["delivery_mode"] in (
        "IN_HOME",
        "HYBRID",
    )

    virtual_rule = None
    if forces_virtual:  # resolved before any write so the request stays atomic
        student = logic.student_of(case)
        virtual_rule = logic.resolve_rule(student["grade_band"], "VIRTUAL_SYNC")
        if virtual_rule is None:
            raise ApiError("ERR_NO_PUBLISHED_ENTITLEMENT_RULE")

    db.set_field(review, "risk_score", score)
    db.set_field(review, "clearance", clearance)
    db.set_field(review, "status", "FINALIZED")
    db.set_field(review, "finalized_by_user_id", middleware.user_id())
    for other in db.by_case("safety_reviews", case["id"]):
        if other["id"] != review["id"] and other["status"] == "FINALIZED":
            db.set_field(other, "status", "SUPERSEDED")

    db.set_field(case, "escort_required", clearance == "CLEARED_WITH_ESCORT")

    if forces_virtual:
        db.set_field(case, "delivery_mode", "VIRTUAL_SYNC")
        db.set_field(case, "entitlement_rule_id", virtual_rule["id"])
        logic.recompute_weekly_entitlement(case, virtual_rule)
        logic.recompute_allocation(case)
        for session in db.by_case("sessions", case["id"]):
            if session["status"] == "SCHEDULED" and session["delivery_mode"] == "IN_HOME":
                db.set_field(session, "status", "CANCELLED_ADMIN")

    db.touch(case)
    return middleware.obj(review)
