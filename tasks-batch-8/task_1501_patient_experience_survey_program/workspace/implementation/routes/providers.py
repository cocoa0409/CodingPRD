"""Provider endpoints (PRD 3.1): npi unique per program."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_DUPLICATE_NPI
from middleware import require_roles
from response import success_object, success_list
from serializers import provider_view
from util import (
    get_json_body, reject_unknown_fields, require_string, get_or_404,
    parse_pagination, paginate, sort_created, query_arg,
)

bp = Blueprint("providers", __name__)


@bp.route("/api/providers", methods=["POST"])
@require_roles("ProgramAdmin")
def create_provider(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"program_id", "full_name", "npi", "specialty"})
    program_id = require_string(body, "program_id")
    full_name = require_string(body, "full_name")
    npi = require_string(body, "npi")
    specialty = require_string(body, "specialty")

    get_or_404(db.programs, program_id, "SurveyProgram")

    for p in db.providers.values():
        if p["program_id"] == program_id and p["npi"] == npi:
            raise_err(ERR_DUPLICATE_NPI, f"npi {npi} already exists in this program")

    provider = db.stamp_new({
        "program_id": program_id,
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
    })
    db.providers[provider["id"]] = provider
    return success_object(provider_view(provider), 201)


@bp.route("/api/providers", methods=["GET"])
@require_roles("Any")
def list_providers(_user_id: str, _role: str):
    items = list(db.providers.values())
    program_id = query_arg("program_id")
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([provider_view(p) for p in page], limit, offset, total)


@bp.route("/api/providers/<providerId>", methods=["GET"])
@require_roles("Any")
def get_provider(providerId: str, _user_id: str, _role: str):
    provider = get_or_404(db.providers, providerId, "Provider")
    return success_object(provider_view(provider))
