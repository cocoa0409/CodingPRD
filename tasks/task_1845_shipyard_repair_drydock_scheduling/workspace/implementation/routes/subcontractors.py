"""Subcontractor registry endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from services.serializers import serialize
from util import get_json_body, require_int, require_string, optional_str_array

bp = Blueprint("subcontractors", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
    "Subcontractor",
)


@bp.route("/v1/subcontractors", methods=["POST"])
@require_roles("YardAdmin")
def create_subcontractor(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    trade_codes = optional_str_array(body, "trade_codes")
    if trade_codes is None:
        if "trade_codes" not in body:
            raise_err(ERR_INVALID_REQUEST, "Missing required field: trade_codes")
        raise_err(ERR_INVALID_REQUEST, "Field trade_codes must be an array of non-empty strings")
    day_rate_cents = require_int(body, "day_rate_cents")
    if day_rate_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "day_rate_cents must be >= 0")

    sub = {
        "name": name,
        "trade_codes": trade_codes,
        "day_rate_cents": day_rate_cents,
    }
    db.stamp_new(sub)
    db.subcontractors[sub["id"]] = sub
    return success_object(serialize(sub), 201)


@bp.route("/v1/subcontractors/<sub_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_subcontractor(sub_id: str, _user_id: str, _role: str):
    sub = db.subcontractors.get(sub_id)
    if sub is None:
        raise_err(ERR_NOT_FOUND, "Subcontractor id does not exist")
    return success_object(serialize(sub))
