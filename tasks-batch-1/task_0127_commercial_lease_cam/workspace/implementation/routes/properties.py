"""Property endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_number,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields

bp = Blueprint("properties", __name__)


@bp.post("/properties")
def create_property():
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    body = get_body()
    require_fields(body, ["name", "total_rentable_sqft"])

    name = body["name"]
    if not isinstance(name, str) or not name:
        raise APIError(ERR_INVALID_REQUEST, 400, "name must be a non-empty string")

    total = body["total_rentable_sqft"]
    if not is_int(total) or total <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "total_rentable_sqft must be a positive integer")

    gross_up = body.get("gross_up_occupancy_pct", 0.95)
    if not is_number(gross_up) or not (0 < gross_up <= 1):
        raise APIError(ERR_INVALID_REQUEST, 400, "gross_up_occupancy_pct must be in (0, 1]")

    prop = {
        **new_common_fields(),
        "name": name,
        "total_rentable_sqft": total,
        "occupied_sqft": 0,
        "gross_up_occupancy_pct": gross_up,
    }
    db.properties[prop["id"]] = prop
    return ok_object(serialize(prop), http_status=201)


@bp.get("/properties/<pid>")
def get_property(pid):
    auth_required(ALL_ROLES)()
    p = db.properties.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Property not found")
    return ok_object(serialize(p))


@bp.get("/properties")
def list_properties():
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    limit, offset = parse_pagination()
    items = order_by_created(list(db.properties.values()))
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/properties/<pid>/leases")
def list_property_leases(pid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    if db.properties.get(pid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Property not found")
    limit, offset = parse_pagination()
    items = order_by_created([l for l in db.leases.values() if l["property_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/properties/<pid>/expense-pools")
def list_property_pools(pid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    if db.properties.get(pid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Property not found")
    limit, offset = parse_pagination()
    items = order_by_created([p for p in db.expense_pools.values() if p["property_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
