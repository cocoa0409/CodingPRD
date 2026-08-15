"""Adjuster endpoints (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from serializers import pub_adjuster
from util import (
    get_json_body,
    optional_field,
    path_or_404,
    require_state_codes,
    require_string,
)
from errors import raise_err, ERR_INVALID_REQUEST

bp = Blueprint("adjusters", __name__)


@bp.post("/siu/adjusters")
@require_roles("SIUManager")
def create_adjuster(_user_id: str, _role: str):
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    state_licenses = require_state_codes(body, "state_licenses")
    active = optional_field(body, "active", True)
    if not isinstance(active, bool):
        raise_err(ERR_INVALID_REQUEST, "Field active must be a boolean")
    adjuster = {
        "full_name": full_name,
        "email": email,
        "state_licenses": state_licenses,
        "active": active,
    }
    db.stamp_new(adjuster)
    db.adjusters[adjuster["id"]] = adjuster
    return success_object(pub_adjuster(adjuster), 201)


@bp.get("/siu/adjusters/<adjusterId>")
@require_roles("Adjuster", "SIUManager", "SIUComplianceOfficer")
def get_adjuster(adjusterId: str, _user_id: str, _role: str):
    adjuster = path_or_404(db.adjusters, adjusterId, "Adjuster")
    return success_object(pub_adjuster(adjuster))
