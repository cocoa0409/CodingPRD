"""Applicant endpoints (PRD §3.2)."""
from flask import Blueprint

import db
from clock import parse_iso
from errors import err
from helpers import get_body, require_fields, serialize
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("applicants", __name__)

GENDERS = {"MALE", "FEMALE"}


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "date_of_birth", "gender", "tobacco_use", "state_code"])
    if body["gender"] not in GENDERS:
        raise err("ERR_VALIDATION", "Invalid gender")
    if not isinstance(body["tobacco_use"], bool):
        raise err("ERR_VALIDATION", "tobacco_use must be a boolean")
    if parse_iso(body["date_of_birth"]) is None:
        raise err("ERR_VALIDATION", "date_of_birth must be a valid ISO 8601 date")

    applicant = {
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "gender": body["gender"],
        "tobacco_use": body["tobacco_use"],
        "state_code": body["state_code"],
    }
    with db.LOCK:
        db.stamp_full(applicant)
        db.applicants[applicant["id"]] = applicant
    return success(serialize(applicant), status=201, response_type="object")


@bp.route("/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin", "ClaimsExaminer"})
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err("ERR_NOT_FOUND", "Applicant not found")
    return success(serialize(applicant), status=200, response_type="object")
