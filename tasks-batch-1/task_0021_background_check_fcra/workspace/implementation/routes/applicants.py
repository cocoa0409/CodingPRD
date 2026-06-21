"""Applicant endpoints."""

from flask import Blueprint

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success
from util import stamp_common_create, get_applicant, get_json_body, require_fields


bp = Blueprint("applicants", __name__)


def _serialize(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "full_name": a["full_name"],
        "email": a["email"],
        "date_of_birth": a["date_of_birth"],
    }


@bp.route("/api/v1/applicants", methods=["POST"])
@require_roles("Applicant", "Recruiter")
def create_applicant(_user_id, _role):
    body = get_json_body()
    require_fields(body, "full_name", "email", "date_of_birth")
    full_name = body["full_name"]
    email = body["email"]
    date_of_birth = body["date_of_birth"]
    if not isinstance(full_name, str) or not full_name.strip():
        raise_api("ERR_INVALID_REQUEST", "full_name must be non-empty string")
    if not isinstance(email, str) or "@" not in email:
        raise_api("ERR_INVALID_REQUEST", "email must be a valid string")
    if not isinstance(date_of_birth, str):
        raise_api("ERR_INVALID_REQUEST", "date_of_birth must be ISO 8601 string")
    try:
        parse_iso(date_of_birth)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "date_of_birth must be ISO 8601")
    email_lc = email.lower()
    for a in db.applicants.values():
        if a["email"] == email_lc:
            raise_api("ERR_INVALID_REQUEST", "email already registered")
    a = {
        "full_name": full_name,
        "email": email_lc,
        "date_of_birth": date_of_birth,
    }
    stamp_common_create(a)
    db.applicants[a["id"]] = a
    return success(_serialize(a), 201)


@bp.route("/api/v1/applicants/<aid>", methods=["GET"])
@require_roles("Applicant", "Recruiter", "ComplianceOfficer")
def get_applicant_route(aid, _user_id, _role):
    a = get_applicant(aid)
    return success(_serialize(a))
