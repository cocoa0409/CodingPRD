"""Self-registration endpoints (Applicant + Attorney). No auth."""
from __future__ import annotations

import re
from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body
from response import ok_object
from services.validation import require_fields, require_string, require_enum


bp = Blueprint("registration", __name__)


ALIEN_NUMBER_RE = re.compile(r"^A\d{9}$")
COUNTRY_CHOICES = {"WORLDWIDE", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"}


@bp.post("/uscis/applicants/register")
def register_applicant():
    body = get_json_body()
    require_fields(body, ["alien_number", "full_name", "date_of_birth", "country_of_chargeability", "email"])
    alien = body["alien_number"]
    full_name = body["full_name"]
    dob = body["date_of_birth"]
    country = body["country_of_chargeability"]
    email = body["email"]

    require_string(alien, "alien_number")
    require_string(full_name, "full_name")
    require_string(dob, "date_of_birth")
    require_string(country, "country_of_chargeability")
    require_string(email, "email")

    if not ALIEN_NUMBER_RE.match(alien):
        raise APIError(ERR_INVALID_REQUEST, 400, "alien_number must match ^A\\d{9}$")
    require_enum(country, COUNTRY_CHOICES, "country_of_chargeability")
    # Validate ISO date.
    try:
        db.parse_iso_date(dob)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "date_of_birth must be ISO YYYY-MM-DD")

    # Uniqueness: alien_number, email
    for a in db.applicants.values():
        if a.get("alien_number") == alien:
            raise APIError(ERR_INVALID_REQUEST, 400, "alien_number already exists")
        if a.get("email") == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already exists")

    applicant = {
        "alien_number": alien,
        "full_name": full_name,
        "date_of_birth": dob,
        "country_of_chargeability": country,
        "email": email,
        "is_under_14": False,  # computed at file_date; default false until then
    }
    db.stamp_common(applicant)
    db.applicants[applicant["id"]] = applicant
    return ok_object(applicant, 201)


@bp.post("/uscis/attorneys/register")
def register_attorney():
    body = get_json_body()
    require_fields(body, ["bar_number", "full_name", "firm_name"])
    bar = body["bar_number"]
    full_name = body["full_name"]
    firm = body["firm_name"]
    require_string(bar, "bar_number")
    require_string(full_name, "full_name")
    require_string(firm, "firm_name")

    for a in db.attorneys.values():
        if a.get("bar_number") == bar:
            raise APIError(ERR_INVALID_REQUEST, 400, "bar_number already exists")

    attorney = {
        "bar_number": bar,
        "full_name": full_name,
        "firm_name": firm,
    }
    db.stamp_common(attorney)
    db.attorneys[attorney["id"]] = attorney
    return ok_object(attorney, 201)
