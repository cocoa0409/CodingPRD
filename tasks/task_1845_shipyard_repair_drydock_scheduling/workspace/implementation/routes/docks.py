"""DockBerth endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from services.serializers import serialize
from util import get_json_body, require_int, require_number, require_string

bp = Blueprint("docks", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
    "Subcontractor",
)


@bp.route("/v1/docks", methods=["POST"])
@require_roles("YardAdmin")
def create_dock(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    max_length_m = require_number(body, "max_length_m")
    max_beam_m = require_number(body, "max_beam_m")
    max_depth_m = require_number(body, "max_depth_m")
    daily_rate_cents = require_int(body, "daily_rate_cents")
    if daily_rate_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "daily_rate_cents must be >= 0")

    dock = {
        "name": name,
        "max_length_m": max_length_m,
        "max_beam_m": max_beam_m,
        "max_depth_m": max_depth_m,
        "daily_rate_cents": daily_rate_cents,
    }
    db.stamp_new(dock)
    db.docks[dock["id"]] = dock
    return success_object(serialize(dock), 201)


@bp.route("/v1/docks/<dock_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_dock(dock_id: str, _user_id: str, _role: str):
    dock = db.docks.get(dock_id)
    if dock is None:
        raise_err(ERR_NOT_FOUND, "DockBerth id does not exist")
    return success_object(serialize(dock))
