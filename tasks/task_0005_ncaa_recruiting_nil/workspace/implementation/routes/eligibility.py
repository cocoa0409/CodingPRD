"""EligibilityCertification endpoints."""

from flask import Blueprint, request

import db
import services
from errors import invalid_request, invalid_state, not_found
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("eligibility", __name__)


DENIAL_REASONS = {"GPA_BELOW_MIN", "AMATEURISM_LOST", "INCOMPLETE_RECORDS"}
CERT_STATUSES = {"PENDING", "APPROVED", "DENIED"}


@bp.post("/ncaa/eligibility-certifications")
def create_cert():
    require_roles("EligibilityCenter")
    body = get_body()
    athlete_id = require_field(body, "student_athlete_id", str)
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    row = {
        "id": db.new_id(),
        "student_athlete_id": athlete_id,
        "status": "PENDING",
        # Snapshot at submission, frozen thereafter
        "gpa_at_review": athlete["gpa"],
        "amateurism_at_review": athlete["amateurism_flag"],
        "denial_reason": None,
    }
    db.stamp_create(row)
    db.eligibility_certifications[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/eligibility-certifications/<cert_id>")
def get_cert(cert_id):
    require_roles("EligibilityCenter", "ComplianceOfficer")
    row = db.eligibility_certifications.get(cert_id)
    if row is None:
        raise not_found("EligibilityCertification not found.")
    return ok_object(row)


@bp.get("/ncaa/eligibility-certifications")
def list_certs():
    require_roles("EligibilityCenter", "ComplianceOfficer")
    limit, offset = parse_pagination()
    athlete = request.args.get("student_athlete_id")
    status = request.args.get("status")
    if status is not None and status not in CERT_STATUSES:
        raise invalid_request("status filter is not a valid enum.")
    rows = list(db.eligibility_certifications.values())
    if athlete is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/ncaa/eligibility-certifications/<cert_id>/approve")
def approve_cert(cert_id):
    require_roles("EligibilityCenter")
    cert = db.eligibility_certifications.get(cert_id)
    if cert is None:
        raise not_found("EligibilityCertification not found.")
    if cert["status"] != "PENDING":
        raise invalid_state("Certification is not in PENDING state.")
    # Preconditions per §1.2: gpa_at_review >= 2.300 AND amateurism_at_review == true
    if cert["gpa_at_review"] < 2.300 or not cert["amateurism_at_review"]:
        raise invalid_state(
            "Certification preconditions not met (gpa_at_review or amateurism_at_review)."
        )
    cert["status"] = "APPROVED"
    db.stamp_update(cert)
    athlete = db.student_athletes.get(cert["student_athlete_id"])
    if athlete is not None:
        athlete["eligibility_status"] = "CERTIFIED"
        db.stamp_update(athlete)
    return ok_object(cert)


@bp.post("/ncaa/eligibility-certifications/<cert_id>/deny")
def deny_cert(cert_id):
    require_roles("EligibilityCenter")
    cert = db.eligibility_certifications.get(cert_id)
    if cert is None:
        raise not_found("EligibilityCertification not found.")
    if cert["status"] != "PENDING":
        raise invalid_state("Certification is not in PENDING state.")
    body = get_body()
    reason = require_field(body, "denial_reason", str)
    require_enum(reason, "denial_reason", DENIAL_REASONS)
    cert["status"] = "DENIED"
    cert["denial_reason"] = reason
    db.stamp_update(cert)
    athlete = db.student_athletes.get(cert["student_athlete_id"])
    if athlete is not None:
        athlete["eligibility_status"] = "INELIGIBLE"
        db.stamp_update(athlete)
        # Cascade: every ScholarshipOffer for this athlete with status in
        # {DRAFT, SENT} auto-WITHDRAWN; SENT cases release slots.
        services.cascade_eligibility_denial(cert["student_athlete_id"])
    return ok_object(cert)
