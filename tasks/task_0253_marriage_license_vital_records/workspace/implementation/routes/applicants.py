"""Applicant endpoints (PRD 3.1)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import success
from util import new_common, serialize, parse_dt
from services.common import get_body, require_fields, require_str, require_enum, lookup

bp = Blueprint("applicants", __name__)

PRIOR_STATUSES = {"NEVER_MARRIED", "DIVORCED", "WIDOWED", "MARRIED"}


@bp.route("/applicants", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_applicant():
    body = get_body()
    require_fields(body, "full_name", "date_of_birth")
    require_str(body["full_name"], "full_name")

    dob = parse_dt(body["date_of_birth"], "date_of_birth")
    if dob >= store.now():
        raise ApiError("ERR_INVALID_REQUEST", "date_of_birth must be a past date")

    prior_status = body.get("prior_marriage_status", "NEVER_MARRIED")
    if prior_status is None:
        prior_status = "NEVER_MARRIED"
    require_enum(prior_status, PRIOR_STATUSES, "prior_marriage_status")

    prior_dissolution = body.get("prior_dissolution_date")
    prior_dissolution_dt = parse_dt(prior_dissolution, "prior_dissolution_date") if prior_dissolution else None

    has_consent = body.get("has_judicial_consent", False)
    if has_consent is None:
        has_consent = False
    if not isinstance(has_consent, bool):
        raise ApiError("ERR_INVALID_REQUEST", "has_judicial_consent must be a boolean")

    ent = new_common("applicant")
    ent.update({
        "full_name": body["full_name"],
        "date_of_birth": dob,
        "prior_marriage_status": prior_status,
        "prior_dissolution_date": prior_dissolution_dt,
        "has_judicial_consent": has_consent,
    })
    store.applicants[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/applicants/<applicant_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant", "WaiverOfficer")
def get_applicant(applicant_id):
    ent = lookup("applicant", applicant_id)
    return success(serialize(ent), status=200)
