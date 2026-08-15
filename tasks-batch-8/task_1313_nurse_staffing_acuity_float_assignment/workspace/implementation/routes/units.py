"""NursingUnit endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_UNIT_NOT_FOUND
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.core import UNIT_TYPES, unit_view
from util import get_json_body, req_str, req_enum, req_int, opt_num

bp = Blueprint("units", __name__)


@bp.post("/units")
@require_roles("NurseAdmin")
def create_unit(_user_id: str, _role: str):
    body = get_json_body()
    name = req_str(body, "name")
    unit_type = req_enum(body, "unit_type", UNIT_TYPES)
    bed_count = req_int(body, "bed_count")
    if bed_count <= 0:
        raise_err(ERR_INVALID_REQUEST, "bed_count must be > 0")
    incentive_budget_cents = req_int(body, "incentive_budget_cents")
    if incentive_budget_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "incentive_budget_cents must be >= 0")
    auto_incentive_multiplier = opt_num(body, "auto_incentive_multiplier", None)

    unit = {
        "name": name,
        "unit_type": unit_type,
        "bed_count": bed_count,
        "incentive_budget_cents": incentive_budget_cents,
        "auto_incentive_multiplier": auto_incentive_multiplier,
    }
    db.stamp_new(unit)
    db.units[unit["id"]] = unit
    return success_object(unit_view(unit), 201)


@bp.get("/units/<unitId>")
@require_roles(*ALL_ROLES)
def get_unit(unitId: str, _user_id: str, _role: str):
    unit = db.units.get(unitId)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "Unit not found")
    return success_object(unit_view(unit))
