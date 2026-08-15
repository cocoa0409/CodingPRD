"""Property endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, base_fields, paginate, err,
)
from response import success_object, success_list
from errors import (
    ERR_PROPERTY_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
)

bp = Blueprint("properties", __name__)


def serialize_property(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "address": p["address"],
        "lot_kind": p["lot_kind"],
        "current_area_sqft": p["current_area_sqft"],
        "open_quote_id": p["open_quote_id"],
        "last_completed_seal_on": p["last_completed_seal_on"],
        "next_seal_eligible_on": p["next_seal_eligible_on"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/api/properties")
def create_property():
    require_role("OfficeAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"customer_id", "address", "lot_kind"})
    require_fields(body, ["customer_id", "address", "lot_kind"])
    customer_id = body["customer_id"]
    if customer_id not in DB.customers:
        raise err(ERR_CUSTOMER_NOT_FOUND, 404, "Customer id does not exist")
    lot_kind = require_enum(body, "lot_kind", {"RESIDENTIAL_DRIVEWAY", "COMMERCIAL_LOT"})
    p = base_fields()
    p.update({
        "customer_id": customer_id,
        "address": body["address"],
        "lot_kind": lot_kind,
        "current_area_sqft": None,
        "open_quote_id": None,
        "last_completed_seal_on": None,
        "next_seal_eligible_on": None,
    })
    DB.properties[p["id"]] = p
    return success_object(serialize_property(p), status=201)


@bp.get("/api/properties")
def list_properties():
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    customer_filter = request.args.get("customer_id")
    items = list(DB.properties.values())
    if role == "Customer":
        items = [p for p in items if p["customer_id"] == user_id]
    if customer_filter:
        items = [p for p in items if p["customer_id"] == customer_filter]
    items.sort(key=lambda p: p["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_property(p) for p in page], limit, offset, total)


@bp.get("/api/properties/<propertyId>")
def get_property(propertyId):
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    p = DB.properties.get(propertyId)
    if p is None:
        raise err(ERR_PROPERTY_NOT_FOUND, 404, "Property id does not exist")
    if role == "Customer" and p["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, 403, "Customer acting on a resource owned by a different customer")
    return success_object(serialize_property(p))
