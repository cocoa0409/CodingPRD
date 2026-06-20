"""Unit CRUD + list (PRD §3.1, §2.5)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)

units_bp = Blueprint("units", __name__)


@units_bp.route("/units", methods=["POST"])
@require_roles("PropertyManager")
def create_unit():
    body = get_json_body()
    require_fields(body, "property_id", "unit_number", "square_feet")

    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")

    unit_number = body["unit_number"]
    if not isinstance(unit_number, str) or not unit_number.strip():
        raise ApiError("ERR_INVALID_REQUEST", "unit_number must be a non-empty string")

    square_feet = body["square_feet"]
    if (not isinstance(square_feet, int) or isinstance(square_feet, bool) or square_feet <= 0):
        raise ApiError("ERR_INVALID_REQUEST", "square_feet must be a positive integer")

    # Duplicate unit_number among the property's non-archived units.
    for u in db.units.values():
        if (u["property_id"] == property_id and u["unit_number"] == unit_number
                and u["status"] != "ARCHIVED"):
            raise ApiError("ERR_DUPLICATE_UNIT_NUMBER", "unit_number already in use")

    record = {
        "property_id": property_id,
        "unit_number": unit_number,
        "square_feet": square_feet,
        "status": "VACANT",
    }
    db.stamp_create(record)
    db.units[record["id"]] = record
    return success(serialize(record), status=201)


@units_bp.route("/units/<unit_id>", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Tenant", "Auditor")
def get_unit(unit_id):
    record = db.units.get(unit_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Unit not found")
    return success(serialize(record), status=200)


@units_bp.route("/units", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def list_units():
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    items = list(db.units.values())
    if property_id is not None:
        items = [u for u in items if u["property_id"] == property_id]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(u) for u in page], limit, offset, total)
