"""Applicant endpoints (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_APPLICANT_NOT_FOUND,
    ERR_SPONSOR_NOT_FOUND,
    ERR_SPONSOR_OWNERSHIP_MISMATCH,
    ERR_SPONSOR_NOT_ACTIVE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.serializers import serialize
from util import (
    fetch_or_404,
    get_json_body,
    require_date_field,
    require_string,
)

bp = Blueprint("applicants", __name__)


@bp.route("/applicants", methods=["POST"])
@require_roles("SponsorSignatory")
def create_applicant(user_id: str, role: str):
    body = get_json_body()
    sponsor_id = require_string(body, "sponsor_id")

    # Priority 3: SponsorSignatory ownership — body's sponsor_id is the caller.
    if sponsor_id != user_id:
        raise_err(
            ERR_SPONSOR_OWNERSHIP_MISMATCH,
            "SponsorSignatory may register applicants only for its own sponsor",
        )

    sponsor = db.STORES["sponsors"].get(sponsor_id)
    if sponsor is None:
        raise_err(ERR_SPONSOR_NOT_FOUND, "No sponsor with the given id")

    full_name = require_string(body, "full_name")
    dob = require_date_field(body, "date_of_birth")
    gov_id = require_string(body, "government_id_number")

    if sponsor["status"] != "ACTIVE":
        raise_err(ERR_SPONSOR_NOT_ACTIVE, "Sponsor must be ACTIVE to register applicants")

    rec = {
        "sponsor_id": sponsor_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "government_id_number": gov_id,
    }
    db.stamp_new(rec)
    db.STORES["applicants"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/applicants/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_applicant(user_id: str, role: str, aid: str):
    applicant = fetch_or_404("applicants", aid, ERR_APPLICANT_NOT_FOUND, "applicant")
    return success_object(serialize(applicant))
