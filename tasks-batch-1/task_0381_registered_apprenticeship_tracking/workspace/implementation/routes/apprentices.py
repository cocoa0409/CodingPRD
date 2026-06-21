"""Apprentice endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    optional_bool,
    parse_pagination,
    require_enum,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from lookups import get_apprentice, get_sponsor
from middleware import require_roles
from response import success_array, success_object

bp = Blueprint("apprentices", __name__)

GENDERS = {"MALE", "FEMALE", "NONBINARY", "UNDISCLOSED"}
RACES = {
    "HISPANIC",
    "WHITE",
    "BLACK",
    "ASIAN",
    "NATIVE_AMERICAN",
    "PACIFIC_ISLANDER",
    "TWO_OR_MORE",
    "UNDISCLOSED",
}


@bp.route("/apprenticeship/apprentices", methods=["POST"])
@require_roles("Sponsor")
def create_apprentice():
    body = get_json_body()
    sponsor_id = require_str(body, "sponsor_id")
    full_name = require_str(body, "full_name")
    gender = require_enum(body, "gender", GENDERS)
    race_ethnicity = require_enum(body, "race_ethnicity", RACES)
    is_veteran = optional_bool(body, "is_veteran", default=False)
    has_disability = optional_bool(body, "has_disability", default=False)

    get_sponsor(sponsor_id)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "sponsor_id": sponsor_id,
            "full_name": full_name,
            "gender": gender,
            "race_ethnicity": race_ethnicity,
            "is_veteran": is_veteran,
            "has_disability": has_disability,
        }
    )
    db.apprentices[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/apprentices", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_apprentices():
    limit, offset = parse_pagination()
    items = list(db.apprentices.values())
    sponsor_id = request.args.get("sponsor_id")
    if sponsor_id is not None:
        items = [a for a in items if a["sponsor_id"] == sponsor_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/apprentices/<aid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_apprentice_route(aid):
    rec = get_apprentice(aid)
    return success_object(serialize(rec))
