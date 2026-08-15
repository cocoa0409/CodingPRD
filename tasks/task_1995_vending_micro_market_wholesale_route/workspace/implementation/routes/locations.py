"""Location endpoints (scaffold §1.5)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role, require_operator_ownership
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_enum, stamp_new
from errors import (
    ApiError, ERR_OPERATOR_NOT_FOUND, ERR_ROUTE_NOT_FOUND, ERR_LOCATION_NOT_FOUND,
)

bp = Blueprint("locations", __name__)

LOCATION_TYPES = {"OFFICE", "SCHOOL", "HOSPITAL", "GYM"}


def view(loc):
    return {k: v for k, v in loc.items()}


@bp.post("/wholesale/locations")
def create_location():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin", "OperatorManager"])
    operator_id = req_string(body, "operator_id")
    name = req_string(body, "name")
    location_type = req_enum(body, "location_type", LOCATION_TYPES)
    route_id = req_string(body, "route_id")
    # Body-referenced existence (tier 6) — but ownership (tier 5) for location create
    # compares payload operator_id; PRD says ownership evaluated after target known to
    # exist. For create, the target is the new resource; payload operator_id check
    # happens after referenced ids resolve.
    if operator_id not in db.operators:
        raise ApiError(ERR_OPERATOR_NOT_FOUND, 404, "Operator id does not exist")
    if route_id not in db.routes:
        raise ApiError(ERR_ROUTE_NOT_FOUND, 404, "DeliveryRoute id does not exist")
    require_operator_ownership(role, user_id, operator_id)
    loc = stamp_new({
        "operator_id": operator_id,
        "name": name,
        "location_type": location_type,
        "route_id": route_id,
        "on_hand_projection": [],
    })
    db.locations[loc["id"]] = loc
    return success_object(view(loc), 201)


@bp.get("/wholesale/locations")
def list_locations():
    get_auth()
    limit, offset = parse_pagination(request.args)
    op_f = request.args.get("operator_id")
    route_f = request.args.get("route_id")
    items = list(db.locations.values())
    if op_f is not None:
        items = [l for l in items if l["operator_id"] == op_f]
    if route_f is not None:
        items = [l for l in items if l["route_id"] == route_f]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    return success_list([view(l) for l in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/locations/<locationId>")
def get_location(locationId):
    get_auth()
    loc = db.locations.get(locationId)
    if loc is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    return success_object(view(loc))


@bp.get("/wholesale/locations/<locationId>/telemetry-events")
def list_location_telemetry(locationId):
    get_auth()
    loc = db.locations.get(locationId)
    if loc is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.telemetry_events.values() if e["location_id"] == locationId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    out = []
    for e in page:
        v = {k: v for k, v in e.items() if k != "recorded_at_dt"}
        out.append(v)
    return success_list(out, limit, offset, total)
