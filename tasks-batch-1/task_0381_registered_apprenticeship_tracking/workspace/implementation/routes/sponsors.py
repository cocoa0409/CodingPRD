"""Sponsor endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from common import (
    get_json_body,
    parse_pagination,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from lookups import get_sponsor
from middleware import require_roles
from response import success_array, success_object

bp = Blueprint("sponsors", __name__)


@bp.route("/apprenticeship/sponsors", methods=["POST"])
@require_roles("RegistrationAgency", "Sponsor")
def create_sponsor():
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    ein = require_str(body, "ein")
    contact_email = require_str(body, "contact_email")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "legal_name": legal_name,
            "ein": ein,
            "contact_email": contact_email,
        }
    )
    db.sponsors[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/sponsors", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_sponsors():
    limit, offset = parse_pagination()
    page, total = sort_and_paginate(list(db.sponsors.values()), limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/sponsors/<sid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_sponsor_route(sid):
    rec = get_sponsor(sid)
    return success_object(serialize(rec))
