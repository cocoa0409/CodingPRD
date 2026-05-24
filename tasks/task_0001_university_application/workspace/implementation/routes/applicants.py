"""Applicant routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, require_field, optional_field
from services import applicants as applicants_service
from services.serializers import serialize_applicant


bp = Blueprint("applicants", __name__)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _validate_gpa(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'gpa' must be a number.")
    if value < 0.0 or value > 4.0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'gpa' must be in 0.0..4.0 inclusive.")
    return float(value)


def _validate_sat(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'sat_total' must be an integer or null.")
    if value < 400 or value > 1600:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'sat_total' must be in 400..1600 inclusive.")
    return value


# --------------------------------------------------------------------------- #
# POST /applicants/register (public)
# --------------------------------------------------------------------------- #

@bp.route("/applicants/register", methods=["POST"])
@require_auth(["Anonymous"])
def register_applicant():
    body = get_json_body()
    email = require_field(body, "email", kind="string")
    full_name = require_field(body, "full_name", kind="string")
    gpa = body.get("gpa")
    if gpa is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'gpa' is required.")
    gpa = _validate_gpa(gpa)
    sat_total = _validate_sat(body.get("sat_total"))

    if not email.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'email' must not be empty.")
    if not full_name.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'full_name' must not be empty.")

    email_normalized = email.strip().lower()

    # Uniqueness check
    for existing in db.applicants.values():
        if existing["email"] == email_normalized:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "An applicant with this email already exists.")

    row = {
        "email": email_normalized,
        "full_name": full_name,
        "gpa": gpa,
        "sat_total": sat_total,
        "profile_status": "DRAFT",
    }
    util.stamp_create(row)
    db.applicants[row["id"]] = row
    # Newly created applicant has no recommenders, so it stays DRAFT.
    return resp.success_object(serialize_applicant(row), http_status=201)


# --------------------------------------------------------------------------- #
# GET /applicants/{id}
# --------------------------------------------------------------------------- #

@bp.route("/applicants/<applicant_id>", methods=["GET"])
@require_auth(["Applicant", "PlatformAdmin"])
def get_applicant(applicant_id):
    row = db.applicants.get(applicant_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Applicant not found.")
    # Ownership for Applicant role
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "Applicant" and user_id != applicant_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicant can only read their own profile.")
    return resp.success_object(serialize_applicant(row))


# --------------------------------------------------------------------------- #
# PATCH /applicants/{id} (owner only)
# --------------------------------------------------------------------------- #

@bp.route("/applicants/<applicant_id>", methods=["PATCH"])
@require_auth(["Applicant"])
def patch_applicant(applicant_id):
    row = db.applicants.get(applicant_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Applicant not found.")
    user_id = request.headers.get("X-User-ID")
    if user_id != applicant_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only update their own profile.")

    body = get_json_body()
    if "full_name" in body:
        if not isinstance(body["full_name"], str) or not body["full_name"].strip():
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'full_name' must be a non-empty string.")
        row["full_name"] = body["full_name"]
    if "gpa" in body:
        if body["gpa"] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'gpa' cannot be null.")
        row["gpa"] = _validate_gpa(body["gpa"])
    if "sat_total" in body:
        row["sat_total"] = _validate_sat(body["sat_total"])

    util.stamp_update(row)
    applicants_service.recompute_profile_status(applicant_id)
    return resp.success_object(serialize_applicant(row))
