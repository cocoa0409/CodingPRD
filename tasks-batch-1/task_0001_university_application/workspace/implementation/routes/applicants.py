"""Applicant endpoints."""
from __future__ import annotations

import re
from flask import Blueprint, request, g

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_PROFILE_LOCKED,
    ERR_FORBIDDEN_OWNER_MISMATCH,
)
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import parse_pagination, paginate, get_body, require_fields, order_by_created_at
from services import calculations
from services.common import new_common_fields, touch

bp = Blueprint("applicants", __name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
RESIDENCY_VALS = {"IN_STATE", "OUT_OF_STATE", "INTERNATIONAL"}


def _validate_gpa(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "gpa_unweighted must be a number")
    fv = float(v)
    if fv < 0.0 or fv > 4.00:
        raise APIError(ERR_INVALID_REQUEST, 400, "gpa_unweighted out of range")
    return fv


def _validate_sat(v):
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "sat_total must be an integer or null")
    if v < 400 or v > 1600:
        raise APIError(ERR_INVALID_REQUEST, 400, "sat_total out of range")
    return v


def _validate_residency(v):
    if v not in RESIDENCY_VALS:
        raise APIError(ERR_INVALID_REQUEST, 400, "residency invalid")
    return v


@bp.post("/applicants")
def create_applicant():
    # Anonymous endpoint
    auth_required({"Anonymous"}, allow_anonymous=True)()
    body = get_body()
    require_fields(body, ["email", "full_name", "gpa_unweighted", "residency"])
    email = body["email"]
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        raise APIError(ERR_INVALID_REQUEST, 400, "Invalid email format")
    email = email.lower()
    # uniqueness
    for a in db.applicants.values():
        if a["email"] == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already registered")
    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name:
        raise APIError(ERR_INVALID_REQUEST, 400, "full_name must be non-empty string")
    gpa = _validate_gpa(body["gpa_unweighted"])
    sat = _validate_sat(body.get("sat_total"))
    residency = _validate_residency(body["residency"])

    common = new_common_fields()
    applicant = {
        **common,
        "email": email,
        "full_name": full_name,
        "gpa_unweighted": gpa,
        "sat_total": sat,
        "residency": residency,
        "profile_status": "DRAFT",
        "submitted_application_count": 0,
    }
    db.applicants[applicant["id"]] = applicant
    return ok_object(applicant, http_status=201)


@bp.get("/applicants/<aid>")
def read_applicant(aid):
    auth_required({"Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"})()
    applicant = db.applicants.get(aid)
    if applicant is None:
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    return ok_object(applicant)


@bp.patch("/applicants/<aid>")
def update_applicant(aid):
    auth_required({"Applicant"})()
    applicant = db.applicants.get(aid)
    if applicant is None:
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    # ownership
    if g.user_id != aid:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this resource")
    body = get_body()

    locked = applicant["profile_status"] == "LOCKED"
    score_recompute = False

    if "full_name" in body:
        if not isinstance(body["full_name"], str) or not body["full_name"]:
            raise APIError(ERR_INVALID_REQUEST, 400, "full_name must be non-empty string")
        applicant["full_name"] = body["full_name"]
    if "gpa_unweighted" in body:
        if locked:
            raise APIError(ERR_PROFILE_LOCKED, 409, "Profile is LOCKED")
        v = _validate_gpa(body["gpa_unweighted"])
        if v != applicant["gpa_unweighted"]:
            applicant["gpa_unweighted"] = v
            score_recompute = True
    if "sat_total" in body:
        if locked:
            raise APIError(ERR_PROFILE_LOCKED, 409, "Profile is LOCKED")
        v = _validate_sat(body["sat_total"])
        if v != applicant["sat_total"]:
            applicant["sat_total"] = v
            score_recompute = True
    if "residency" in body:
        if locked:
            raise APIError(ERR_PROFILE_LOCKED, 409, "Profile is LOCKED")
        applicant["residency"] = _validate_residency(body["residency"])
    touch(applicant)
    if score_recompute:
        for app in db.applications.values():
            if app["applicant_id"] == aid and app["status"] in {"SUBMITTED", "UNDER_REVIEW"}:
                calculations.recompute_application_composite(app)
    return ok_object(applicant)


@bp.get("/applicants")
def list_applicants():
    auth_required({"AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"})()
    residency = request.args.get("residency")
    limit, offset = parse_pagination()
    items = [a for a in db.applicants.values()
             if residency is None or a["residency"] == residency]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)
