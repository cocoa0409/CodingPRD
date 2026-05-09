"""Property CRUD endpoints."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_DUPLICATE_PROPERTY,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.common import stamp_create
from services.voting_status import recompute_for_owner
from utils import get_body, require_field, to_decimal

bp = Blueprint("properties", __name__)


@bp.post("/properties")
@require_roles("PropertyManager")
def create_property():
    body = get_body()
    building_no = require_field(body, "building_no")
    unit_no = require_field(body, "unit_no")
    area_sqm = require_field(body, "area_sqm")
    owner_id = require_field(body, "owner_id")
    parking_quota = body.get("parking_quota", 1)

    # area_sqm > 0
    try:
        area_dec = to_decimal(area_sqm)
    except APIError:
        raise APIError(ERR_VALIDATION, "area_sqm must be numeric.", 422)
    if area_dec <= 0:
        raise APIError(ERR_VALIDATION, "area_sqm must be > 0.", 422)

    if owner_id not in db.owners:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Owner {owner_id} not found.", 404)

    # Uniqueness on (building_no, unit_no)
    for existing in db.properties.values():
        if existing.get("building_no") == building_no and existing.get("unit_no") == unit_no:
            raise APIError(
                ERR_DUPLICATE_PROPERTY,
                f"Property {building_no}-{unit_no} already exists.",
                409,
            )

    if not isinstance(parking_quota, int) or parking_quota < 0:
        raise APIError(ERR_VALIDATION, "parking_quota must be a non-negative integer.", 422)

    prop = {
        "building_no": building_no,
        "unit_no": unit_no,
        "area_sqm": float(area_dec),
        "owner_id": owner_id,
        "parking_quota": parking_quota,
        "occupancy_status": "VACANT",
    }
    stamp_create(prop)
    db.properties[prop["id"]] = prop

    # New property may flip an INELIGIBLE_NO_PROPERTY owner back to ELIGIBLE.
    recompute_for_owner(owner_id)
    return success(prop, status=201)


@bp.get("/properties/<pid>")
@require_roles("PropertyManager", "Owner")
def get_property(pid):
    prop = db.properties.get(pid)
    if prop is None:
        raise APIError(ERR_NOT_FOUND, f"Property {pid} not found.", 404)
    if g.user_role == "Owner" and prop.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Owners may only view their own properties.", 403)
    return success(prop)
