"""Vessel endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from services.serializers import serialize
from util import get_json_body, require_number, require_string

bp = Blueprint("vessels", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
    "Subcontractor",
)


@bp.route("/v1/vessels", methods=["POST"])
@require_roles("ProjectManager")
def create_vessel(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    imo_number = require_string(body, "imo_number")
    length_m = require_number(body, "length_m")
    beam_m = require_number(body, "beam_m")
    draft_m = require_number(body, "draft_m")
    owner_user_id = require_string(body, "owner_user_id")

    # imo_number is unique across vessels.
    if any(v["imo_number"] == imo_number for v in db.vessels.values()):
        raise_err(ERR_INVALID_REQUEST, "imo_number must be unique across vessels")

    vessel = {
        "name": name,
        "imo_number": imo_number,
        "length_m": length_m,
        "beam_m": beam_m,
        "draft_m": draft_m,
        "owner_user_id": owner_user_id,
    }
    db.stamp_new(vessel)
    db.vessels[vessel["id"]] = vessel
    return success_object(serialize(vessel), 201)


@bp.route("/v1/vessels/<vessel_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_vessel(vessel_id: str, _user_id: str, _role: str):
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        raise_err(ERR_NOT_FOUND, "Vessel id does not exist")
    return success_object(serialize(vessel))
