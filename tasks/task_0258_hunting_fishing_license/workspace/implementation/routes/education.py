"""EducationCertificate endpoints (PRD §3.2)."""
from flask import Blueprint, request

import serialize
from db import store
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, parse_pagination, paginate,
)
from services.core import (
    get_applicant_or_404, get_education_certificate_or_404,
)

bp = Blueprint("education", __name__)


@bp.route("/education-certificates", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def create_education_certificate():
    body = get_json_body()
    applicant_id = as_nonempty_str(body, "applicant_id", required=True)
    course_code = as_nonempty_str(body, "course_code", required=True)
    completion_date = as_nonempty_str(body, "completion_date", required=True)

    get_applicant_or_404(applicant_id)

    record = {
        "applicant_id": applicant_id,
        "course_code": course_code,
        "completion_date": completion_date,
        "status": "PENDING",
    }
    store.stamp_new(record)
    store.education_certificates[record["id"]] = record
    return success(
        serialize.education_certificate(record), status=201, response_type="object"
    )


@bp.route("/education-certificates/<id>", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def get_education_certificate(id):
    record = get_education_certificate_or_404(id)
    return success(
        serialize.education_certificate(record), status=200, response_type="object"
    )


@bp.route("/education-certificates", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def list_education_certificates():
    limit, offset = parse_pagination()
    items = list(store.education_certificates.values())
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        items = [r for r in items if r["applicant_id"] == applicant_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.education_certificate(r) for r in page], limit, offset, total
    )


@bp.route("/education-certificates/<id>/verify", methods=["POST"])
@require_roles("DrawOfficer")
def verify_education_certificate(id):
    record = get_education_certificate_or_404(id)
    if record["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Certificate is not PENDING")
    record["status"] = "VERIFIED"
    store.touch(record)
    # Cross-entity write: set Applicant.education_certified = true (PRD §3.2).
    applicant = store.applicants.get(record["applicant_id"])
    if applicant is not None:
        applicant["education_certified"] = True
        store.touch(applicant)
    return success(
        serialize.education_certificate(record), status=200, response_type="object"
    )


@bp.route("/education-certificates/<id>/reject", methods=["POST"])
@require_roles("DrawOfficer")
def reject_education_certificate(id):
    record = get_education_certificate_or_404(id)
    if record["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Certificate is not PENDING")
    record["status"] = "REJECTED"
    store.touch(record)
    # education_certified left unchanged (PRD §3.2).
    return success(
        serialize.education_certificate(record), status=200, response_type="object"
    )
