"""Completion certificate read endpoints (PRD §3.7). Certificates are created as a
cascade of agreement completion; there is no POST."""
from flask import Blueprint, request

import db
from common import (
    parse_pagination,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from lookups import get_certificate
from middleware import require_roles
from response import success_array, success_object

bp = Blueprint("certificates", __name__)


@bp.route("/apprenticeship/certificates", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_certificates():
    limit, offset = parse_pagination()
    items = list(db.certificates.values())
    for key in ("agreement_id", "program_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/certificates/<cid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_certificate_route(cid):
    rec = get_certificate(cid)
    return success_object(serialize(rec))
