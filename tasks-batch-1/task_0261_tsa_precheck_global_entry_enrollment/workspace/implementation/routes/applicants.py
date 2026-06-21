"""Applicant registration & reads (PRD §3.2).

An Applicant has full_name, date_of_birth (YYYY-MM-DD), citizenship in
{US_CITIZEN, LPR, NONIMMIGRANT}, and an optional disqualifying_flag (default
false).
"""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_bool,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
)
from services.lookups import get_or_404

bp = Blueprint("applicants", __name__)


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    require_auth(["Applicant", "SchedulingAdmin"])
    body = get_body()
    require_fields(body, ["full_name", "date_of_birth", "citizenship"])
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    citizenship = require_enum(body, "citizenship", ["US_CITIZEN", "LPR", "NONIMMIGRANT"])
    disqualifying = optional_bool(body, "disqualifying_flag", default=False)

    rec = {
        "full_name": full_name,
        "date_of_birth": dob,
        "citizenship": citizenship,
        "disqualifying_flag": disqualifying,
    }
    stamp_create(rec)
    db.applicants[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    require_auth(["Applicant", "SchedulingAdmin", "VettingOfficer"])
    rec = get_or_404(db.applicants, aid, "Applicant")
    return ok_object(serialize(rec), 200)


@bp.route("/applicants/<aid>/applications", methods=["GET"])
def list_applicant_applications(aid):
    require_auth(["Applicant", "SchedulingAdmin", "VettingOfficer"])
    get_or_404(db.applicants, aid, "Applicant")
    limit, offset = parse_pagination()
    items = [a for a in db.applications.values() if a.get("applicant_id") == aid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
