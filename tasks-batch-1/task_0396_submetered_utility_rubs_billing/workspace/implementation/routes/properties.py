"""Property CRUD (PRD §3.1, §2.7, §2.8)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import require_roles
from response import success
from services.common import get_json_body, require_fields, serialize

properties_bp = Blueprint("properties", __name__)

VALID_STATES = {"CA", "TX", "NY", "FL"}


def _validate_pct(value, field, lo_inclusive, hi, hi_inclusive):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    v = float(value)
    if lo_inclusive:
        if v < 0:
            raise ApiError("ERR_INVALID_REQUEST", "%s out of range" % field)
    else:
        if v <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "%s out of range" % field)
    if hi_inclusive:
        if v > hi:
            raise ApiError("ERR_INVALID_REQUEST", "%s out of range" % field)
    else:
        if v >= hi:
            raise ApiError("ERR_INVALID_REQUEST", "%s out of range" % field)


@properties_bp.route("/properties", methods=["POST"])
@require_roles("PropertyManager")
def create_property():
    body = get_json_body()
    require_fields(body, "name", "state_code")

    name = body["name"]
    state_code = body["state_code"]
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(state_code, str) or state_code not in VALID_STATES:
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be one of CA, TX, NY, FL")

    # recovery_cap_pct: 0 < x <= 1, default 0.85
    recovery_cap_pct = body.get("recovery_cap_pct", 0.85)
    _validate_pct(recovery_cap_pct, "recovery_cap_pct", lo_inclusive=False, hi=1, hi_inclusive=True)
    # common_area_pct: 0 <= x < 1, default 0.10
    common_area_pct = body.get("common_area_pct", 0.10)
    _validate_pct(common_area_pct, "common_area_pct", lo_inclusive=True, hi=1, hi_inclusive=False)

    record = {
        "name": name,
        "state_code": state_code,
        "recovery_cap_pct": recovery_cap_pct,
        "common_area_pct": common_area_pct,
        "current_period_label": None,
        "integrity_status": "OK",
    }
    db.stamp_create(record)
    db.properties[record["id"]] = record
    return success(serialize(record), status=201)


@properties_bp.route("/properties/<property_id>", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Tenant", "Auditor")
def get_property(property_id):
    record = db.properties.get(property_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Property not found")
    return success(serialize(record), status=200)
