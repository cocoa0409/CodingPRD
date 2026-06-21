"""Utility CRUD + list (PRD §3.1, §2.5)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)

utilities_bp = Blueprint("utilities", __name__)

VALID_UTILITY_TYPES = {"WATER", "ELECTRIC", "GAS"}
VALID_ALLOCATION_METHODS = {"CONSUMPTION", "RUBS"}


@utilities_bp.route("/utilities", methods=["POST"])
@require_roles("PropertyManager")
def create_utility():
    body = get_json_body()
    require_fields(body, "property_id", "utility_type", "allocation_method", "unit_of_measure")

    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")

    utility_type = body["utility_type"]
    if utility_type not in VALID_UTILITY_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "utility_type must be WATER, ELECTRIC, or GAS")
    allocation_method = body["allocation_method"]
    if allocation_method not in VALID_ALLOCATION_METHODS:
        raise ApiError("ERR_INVALID_REQUEST", "allocation_method must be CONSUMPTION or RUBS")
    unit_of_measure = body["unit_of_measure"]
    if not isinstance(unit_of_measure, str) or not unit_of_measure.strip():
        raise ApiError("ERR_INVALID_REQUEST", "unit_of_measure must be a non-empty string")

    monthly_admin_fee_cents = body.get("monthly_admin_fee_cents", 0)
    if (not isinstance(monthly_admin_fee_cents, int) or isinstance(monthly_admin_fee_cents, bool)
            or monthly_admin_fee_cents < 0):
        raise ApiError("ERR_INVALID_REQUEST", "monthly_admin_fee_cents must be a non-negative integer")

    record = {
        "property_id": property_id,
        "utility_type": utility_type,
        "allocation_method": allocation_method,
        "unit_of_measure": unit_of_measure,
        "monthly_admin_fee_cents": monthly_admin_fee_cents,
        "status": "ACTIVE",
    }
    db.stamp_create(record)
    db.utilities[record["id"]] = record
    return success(serialize(record), status=201)


@utilities_bp.route("/utilities/<utility_id>", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Tenant", "Auditor")
def get_utility(utility_id):
    record = db.utilities.get(utility_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Utility not found")
    return success(serialize(record), status=200)


@utilities_bp.route("/utilities", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def list_utilities():
    property_id = request.args.get("property_id")
    utility_type = request.args.get("utility_type")
    items = list(db.utilities.values())
    if property_id is not None:
        items = [u for u in items if u["property_id"] == property_id]
    if utility_type is not None:
        items = [u for u in items if u["utility_type"] == utility_type]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(u) for u in page], limit, offset, total)
