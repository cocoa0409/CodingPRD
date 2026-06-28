from flask import Blueprint, request

from db import db, common_create_fields
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_body, require_fields, as_str, as_int,
    get_customer, get_route, get_property,
    get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("properties", __name__)


@bp.post("/properties")
def create_property():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["customer_id", "route_id", "address", "stories"])
    # Existence checked left-to-right (parent ids) before body well-formedness
    # of scalar fields per PRD §2.7 ordering (existence priority 3 < body 5).
    customer = get_customer(body["customer_id"])
    route = get_route(body["route_id"])
    address = as_str(body["address"], "address")
    stories = as_int(body["stories"], "stories", minimum=1)
    roof = 0
    siding = 0
    concrete = 0
    if "roof_sqft" in body and body["roof_sqft"] is not None:
        roof = as_int(body["roof_sqft"], "roof_sqft", minimum=0)
    if "siding_sqft" in body and body["siding_sqft"] is not None:
        siding = as_int(body["siding_sqft"], "siding_sqft", minimum=0)
    if "concrete_sqft" in body and body["concrete_sqft"] is not None:
        concrete = as_int(body["concrete_sqft"], "concrete_sqft", minimum=0)
    p = common_create_fields()
    p.update({
        "customer_id": customer["id"],
        "route_id": route["id"],
        "address": address,
        "stories": stories,
        "roof_sqft": roof,
        "siding_sqft": siding,
        "concrete_sqft": concrete,
    })
    db.properties[p["id"]] = p
    return success(serialize.property_view(p), 201)


@bp.get("/properties")
def list_properties():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    customer_id = request.args.get("customer_id")
    route_id = request.args.get("route_id")
    limit, offset = get_pagination()
    items = []
    for p in db.properties.values():
        if customer_id is not None and p["customer_id"] != customer_id:
            continue
        if route_id is not None and p["route_id"] != route_id:
            continue
        if role == "Customer" and p["customer_id"] != user_id:
            continue
        items.append(p)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.property_view(p) for p in page], limit, offset, total)


@bp.get("/properties/<pid>")
def get_one_property(pid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    p = get_property(pid)
    if role == "Customer" and p["customer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.property_view(p), 200)
