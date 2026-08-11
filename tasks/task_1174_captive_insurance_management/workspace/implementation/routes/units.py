"""OperatingUnit routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    get_captive,
    get_unit,
    req_enum,
    req_num,
    req_str,
    stamp_new,
)

bp = Blueprint("units", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter", "Actuary")


@bp.post("/api/captives/<captiveId>/operating-units")
def create_unit(captiveId):
    user_id, role = require_roles("CaptiveManager")
    get_captive(captiveId)
    data = body()
    name = req_str(data, "unit_name")
    code = req_str(data, "unit_code")
    basis = req_enum(data, "exposure_basis", C.EXPOSURE_BASES)
    exposure = req_num(data, "exposure_amount")
    if exposure < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "exposure_amount must be a non-negative number")

    unit = stamp_new()
    unit.update({
        "captive_id": captiveId,
        "unit_name": name,
        "unit_code": code,
        "exposure_basis": basis,
        "exposure_amount": exposure,
        "total_premium_allocated_cents": 0,
        "total_claims_incurred_cents": 0,
        "loss_ratio": 0.0,
        "status": "ACTIVE",
    })
    db.units[unit["id"]] = unit
    log(captiveId, "STATE_CHANGE", "OperatingUnit", unit["id"], role, user_id,
        "Operating unit created ACTIVE", None, "ACTIVE")
    return ok(unit, 201)


@bp.get("/api/captives/<captiveId>/operating-units")
def list_units(captiveId):
    require_roles(*READ_ROLES)
    get_captive(captiveId)
    items = sorted(
        [u for u in db.units.values() if u["captive_id"] == captiveId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/operating-units/<unitId>")
def get_unit_route(captiveId, unitId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    return ok(get_unit(captive, unitId), 200)
