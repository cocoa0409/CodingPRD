"""Physician certification and the path to eligibility (PRD §3.2)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import CERT_STATUSES, DIAGNOSIS_CATEGORIES, listing
from services import logic
from validation import parse_date

bp = Blueprint("certifications", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "NurseReviewer"]

SIGNATURE_LOOKBACK_DAYS = 30
MIN_ABSENCE_DAYS = 10

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "physician_npi": {"type": "string", "required": True, "npi": True},
    "diagnosis_category": {
        "type": "string",
        "required": True,
        "enum": DIAGNOSIS_CATEGORIES,
    },
    "certified_start_date": {"type": "date", "required": True},
    "certified_end_date": {"type": "date", "required": True},
    "expected_absence_days": {"type": "integer", "required": True, "min": 1},
    "signature_date": {"type": "date", "required": True},
    "expected_case_version": {"type": "integer", "required": True},
    "clinical_note": {"type": "string"},
}

REVIEW_BODY = {
    "decision": {"type": "string", "required": True, "enum": ["ACCEPT", "REJECT"]},
    "review_note": {"type": "string"},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "status": {"type": "string", "enum": CERT_STATUSES},
    "is_current": {"type": "boolean"},
}


@bp.post("/hhi/certifications")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_certification():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                     # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    if body["expected_case_version"] != case["version"]:        # tier 7
        raise ApiError("ERR_STALE_CASE_VERSION")

    for cert in db.by_case("certifications", case["id"]):       # tier 8
        if cert["status"] == "SUBMITTED":
            raise ApiError("ERR_CERT_ALREADY_PENDING")
    if case["service_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CASE_STATE")

    student = logic.student_of(case)
    if student["enrollment_status"] != "ENROLLED":              # tier 12
        raise ApiError("ERR_STUDENT_NOT_ENROLLED")

    start = parse_date(body["certified_start_date"])
    end = parse_date(body["certified_end_date"])
    signed = parse_date(body["signature_date"])
    if (
        end < start
        or signed > clock.get_date()
        or signed < start - timedelta(days=SIGNATURE_LOOKBACK_DAYS)
    ):
        raise ApiError("ERR_CERT_WINDOW_INVALID")

    row = db.insert(
        "certifications",
        {
            "case_id": case["id"],
            "physician_npi": body["physician_npi"],
            "diagnosis_category": body["diagnosis_category"],
            "certified_start_date": body["certified_start_date"],
            "certified_end_date": body["certified_end_date"],
            "expected_absence_days": body["expected_absence_days"],
            "signature_date": body["signature_date"],
            "status": "SUBMITTED",
            "is_current": False,
            "submitted_by_user_id": middleware.user_id(),
            "reviewed_by_user_id": None,
            "clinical_note": body.get("clinical_note"),
            "review_note": None,
        },
    )

    db.set_field(case, "service_status", "PENDING_CERT_REVIEW")
    db.touch(case)
    return middleware.obj(row)


@bp.get("/hhi/certifications/<certification_id>")
@endpoint(READ_ROLES)
def read_certification(certification_id):
    row = db.get("certifications", certification_id)
    if row is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/certifications")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_certifications():
    return listing("certifications", LIST_QUERY)


@bp.post("/hhi/certifications/<certification_id>/review")
@endpoint(["NurseReviewer"], body=REVIEW_BODY)
def review_certification(certification_id):
    cert = db.get("certifications", certification_id)
    if cert is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "SUBMITTED":                            # tier 8
        raise ApiError("ERR_CERT_NOT_REVIEWABLE")

    body = middleware.body()
    case = db.get("cases", cert["case_id"])

    if body["decision"] == "REJECT":
        db.set_field(cert, "status", "REJECTED")
        db.set_field(cert, "reviewed_by_user_id", middleware.user_id())
        if "review_note" in body:
            db.set_field(cert, "review_note", body["review_note"])
        db.set_field(case, "service_status", "DRAFT")
        db.touch(case)
        return middleware.obj(cert)

    # ACCEPT: every precondition is checked before the first write.
    if cert["expected_absence_days"] < MIN_ABSENCE_DAYS:
        raise ApiError("ERR_ABSENCE_DURATION_TOO_SHORT")
    student = logic.student_of(case)
    rule = logic.resolve_rule(student["grade_band"], case["delivery_mode"])
    if rule is None:
        raise ApiError("ERR_NO_PUBLISHED_ENTITLEMENT_RULE")

    for other in db.by_case("certifications", case["id"]):
        if other["id"] != cert["id"] and other["is_current"]:
            db.set_field(other, "status", "SUPERSEDED")
            db.set_field(other, "is_current", False)

    db.set_field(cert, "status", "ACCEPTED")
    db.set_field(cert, "is_current", True)
    db.set_field(cert, "reviewed_by_user_id", middleware.user_id())
    if "review_note" in body:
        db.set_field(cert, "review_note", body["review_note"])

    db.set_field(case, "service_status", "ELIGIBLE")
    db.set_field(case, "diagnosis_category", cert["diagnosis_category"])
    db.set_field(case, "certified_start_date", cert["certified_start_date"])
    db.set_field(case, "certified_end_date", cert["certified_end_date"])
    db.set_field(
        case,
        "certification_count",
        len([c for c in db.by_case("certifications", case["id"]) if c["status"] == "ACCEPTED"]),
    )
    db.set_field(case, "entitlement_rule_id", rule["id"])
    logic.recompute_weekly_entitlement(case, rule)
    logic.recompute_allocation(case)
    db.touch(case)
    return middleware.obj(cert)
