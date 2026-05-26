"""RecommendationRequest endpoints."""
from __future__ import annotations

import re
from flask import Blueprint, request, g

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FORBIDDEN_OWNER_MISMATCH,
)
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, get_body, require_fields, order_by_created_at,
)
from services import state_machines
from services.common import new_common_fields

bp = Blueprint("recommendations", __name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


@bp.post("/recommendation-requests")
def create_rr():
    auth_required({"Applicant"})()
    body = get_body()
    require_fields(body, ["applicant_id", "school_id", "recommender_email"])
    applicant_id = body["applicant_id"]
    school_id = body["school_id"]
    if applicant_id not in db.applicants:
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    if school_id not in db.schools:
        raise APIError(ERR_NOT_FOUND, 404, "School not found")
    if g.user_id != applicant_id:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this applicant")
    email = body["recommender_email"]
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        raise APIError(ERR_INVALID_REQUEST, 400, "recommender_email invalid")
    # uniqueness
    for r in db.recommendation_requests.values():
        if (r["applicant_id"] == applicant_id and r["school_id"] == school_id
                and r["recommender_email"] == email):
            raise APIError(ERR_INVALID_REQUEST, 400,
                           "Duplicate recommendation request")
    common = new_common_fields()
    rr = {
        **common,
        "applicant_id": applicant_id,
        "school_id": school_id,
        "recommender_email": email,
        "status": "INVITED",
        "submitted_at": None,
        "rating": None,
    }
    db.recommendation_requests[rr["id"]] = rr
    return ok_object(rr, http_status=201)


@bp.post("/recommendation-requests/<rid>/submit")
def rec_submit(rid):
    auth_required({"PlatformAdmin"})()
    rr = db.recommendation_requests.get(rid)
    if rr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Recommendation request not found")
    body = get_body()
    if "rating" not in body:
        raise APIError(ERR_INVALID_REQUEST, 400, "rating required")
    state_machines.rec_submit(rr, body["rating"])
    return ok_object(rr)


@bp.post("/recommendation-requests/<rid>/waive")
def rec_waive(rid):
    auth_required({"Applicant"})()
    rr = db.recommendation_requests.get(rid)
    if rr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Recommendation request not found")
    if g.user_id != rr["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this recommendation request")
    state_machines.rec_waive(rr)
    return ok_object(rr)


@bp.get("/recommendation-requests/<rid>")
def read_rr(rid):
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    rr = db.recommendation_requests.get(rid)
    if rr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Recommendation request not found")
    if g.user_role == "Applicant" and g.user_id != rr["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this recommendation request")
    return ok_object(rr)


@bp.get("/recommendation-requests")
def list_rr():
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    applicant_id = request.args.get("applicant_id")
    school_id = request.args.get("school_id")
    status_f = request.args.get("status")
    limit, offset = parse_pagination()
    items = []
    for r in db.recommendation_requests.values():
        if applicant_id and r["applicant_id"] != applicant_id:
            continue
        if school_id and r["school_id"] != school_id:
            continue
        if status_f and r["status"] != status_f:
            continue
        if g.user_role == "Applicant" and r["applicant_id"] != g.user_id:
            continue
        items.append(r)
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)
