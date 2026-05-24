"""EmploymentCertification endpoints."""
from __future__ import annotations

import re

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CERTIFICATION_FIELDS_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import loan_ops, serializer

bp = Blueprint("employment_certifications", __name__)

VALID_EMPLOYER_TYPES = {
    "GOVERNMENT_FEDERAL",
    "GOVERNMENT_STATE_LOCAL_TRIBAL",
    "NONPROFIT_501C3",
    "OTHER_NONPROFIT_QUALIFYING",
    "FOR_PROFIT",
    "NOT_QUALIFYING",
}


@bp.post("/v1/employment-certifications")
@require_roles({"LoanServicer", "Borrower"})
def create_certification():
    body = parse_json_body()
    borrower_id = get_field(body, "borrower_id")
    employer_ein = get_field(body, "employer_ein")
    employer_type = get_field(body, "employer_type")
    period_start_on = get_field(body, "period_start_on")
    period_end_on = get_field(body, "period_end_on")
    weekly_hours = get_field(body, "weekly_hours")

    must_get(db.borrowers, borrower_id, "Borrower")
    if current_role() == "Borrower" and current_user_id() != borrower_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this resource")

    if employer_type not in VALID_EMPLOYER_TYPES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid employer_type")
    if not isinstance(employer_ein, str) or not re.fullmatch(r"\d{9}", employer_ein):
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "employer_ein must be 9 digits")
    if not isinstance(period_start_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_start_on):
        raise APIError(ERR_INVALID_REQUEST, "period_start_on must be YYYY-MM-DD")
    if not isinstance(period_end_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end_on):
        raise APIError(ERR_INVALID_REQUEST, "period_end_on must be YYYY-MM-DD")
    if period_end_on < period_start_on:
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "period_end_on before period_start_on")
    if not isinstance(weekly_hours, (int, float)) or isinstance(weekly_hours, bool):
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "weekly_hours must be a number")
    if float(weekly_hours) < 0 or float(weekly_hours) > 80:
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "weekly_hours out of [0, 80]")

    cid = db.new_id()
    now = db.now_iso()
    cert = {
        "id": cid,
        "borrower_id": borrower_id,
        "employer_ein": employer_ein,
        "employer_type": employer_type,
        "period_start_on": period_start_on,
        "period_end_on": period_end_on,
        "weekly_hours": weekly_hours,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.employment_certifications[cid] = cert
    return success(serializer.serialize_cert(cert), status=201)


@bp.post("/v1/employment-certifications/<cert_id>/approve")
@require_roles({"LoanServicer"})
def approve_certification(cert_id):
    cert = must_get(db.employment_certifications, cert_id, "EmploymentCertification")
    if cert["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Certification not PENDING")
    # Re-verify the fields at approval per §3.6
    if not re.fullmatch(r"\d{9}", cert["employer_ein"]):
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "employer_ein invalid")
    if cert["period_end_on"] < cert["period_start_on"]:
        raise APIError(ERR_CERTIFICATION_FIELDS_INVALID, "period_end_on before period_start_on")

    cert["status"] = "APPROVED"
    serializer.bump_cert(cert)
    # Trigger PSLF recount for the borrower
    loan_ops.maybe_recount_for_borrower(cert["borrower_id"])
    return success(serializer.serialize_cert(cert), status=200)


@bp.post("/v1/employment-certifications/<cert_id>/reject")
@require_roles({"LoanServicer"})
def reject_certification(cert_id):
    cert = must_get(db.employment_certifications, cert_id, "EmploymentCertification")
    if cert["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Certification not PENDING")
    cert["status"] = "REJECTED"
    serializer.bump_cert(cert)
    return success(serializer.serialize_cert(cert), status=200)


@bp.get("/v1/employment-certifications")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def list_certifications():
    limit, offset = parse_pagination()
    borrower_filter = request.args.get("borrower_id")
    status_filter = request.args.get("status")
    items = list(db.employment_certifications.values())
    if current_role() == "Borrower":
        items = [c for c in items if c["borrower_id"] == current_user_id()]
    if borrower_filter:
        items = [c for c in items if c["borrower_id"] == borrower_filter]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_cert(c) for c in page], limit, offset, total)
