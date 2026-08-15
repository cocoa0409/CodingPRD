"""Route endpoints: create/get/list, activate/suspend/retire with cascades."""

from flask import Blueprint

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_enum,
    base_fields, paginate, err, touch, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_DISTRIBUTOR_NOT_FOUND, ERR_ROUTE_NOT_FOUND,
    ERR_ROUTE_NOT_ACTIVE, ERR_ROUTE_HAS_OPEN_ORDERS,
)
from serializers import serialize_route, serialize_store
from services import refresh_trip_loaded_cases

bp = Blueprint("dairy_routes", __name__)

WEEKDAY_CODES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
OPEN_LISTING_STATES = {"DRAFT", "LISTED", "OFFER_PENDING", "UNDER_CONTRACT"}


@bp.post("/dairy/routes")
def create_route():
    require_role("TerritoryManager")
    body = get_json_body()
    check_unknown_fields(
        body, {"distributor_id", "route_code", "name", "service_weekdays",
               "credit_price_basis"})
    require_fields(body, ["distributor_id", "route_code", "name", "service_weekdays"])
    distributor = DB.distributors.get(body["distributor_id"])
    if distributor is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Distributor id not found")
    route_code = body["route_code"]
    if not isinstance(route_code, str):
        raise err(ERR_INVALID_REQUEST, "route_code must be a string")
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_REQUEST, "name must be a string")
    weekdays = body["service_weekdays"]
    if (not isinstance(weekdays, list)
            or any((not isinstance(w, str)) or w not in WEEKDAY_CODES for w in weekdays)):
        raise err(ERR_INVALID_REQUEST, "service_weekdays must be an array of MON..SUN codes")
    credit_price_basis = opt_enum(body, "credit_price_basis", {"ORIGINAL", "CURRENT"})
    if credit_price_basis is None:
        credit_price_basis = "ORIGINAL"
    for r in DB.routes.values():
        if r["route_code"] == route_code:
            raise err(ERR_INVALID_REQUEST, "route_code must be unique")
    r = base_fields()
    r.update({
        "distributor_id": distributor["id"],
        "route_code": route_code,
        "name": name,
        "service_weekdays": list(weekdays),
        "credit_price_basis": credit_price_basis,
        "status": "DRAFT",
    })
    DB.routes[r["id"]] = r
    return success_object(serialize_route(r), status=201)


@bp.get("/dairy/routes/<routeId>")
def get_route(routeId):
    require_any()
    r = DB.routes.get(routeId)
    if r is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    return success_object(serialize_route(r))


@bp.get("/dairy/distributors/<distId>/routes")
def list_distributor_routes(distId):
    require_any()
    d = DB.distributors.get(distId)
    if d is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Distributor id not found")
    items = [r for r in DB.routes.values() if r["distributor_id"] == distId]
    items.sort(key=lambda r: r["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_route(r) for r in page], limit, offset, total)


@bp.get("/dairy/routes/<routeId>/stores")
def list_route_stores(routeId):
    require_any()
    r = DB.routes.get(routeId)
    if r is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    items = [s for s in DB.stores.values() if s["route_id"] == routeId]
    items.sort(key=lambda s: s["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_store(s) for s in page], limit, offset, total)


@bp.post("/dairy/routes/<routeId>/activate")
def activate_route(routeId):
    require_role("TerritoryManager")
    r = DB.routes.get(routeId)
    if r is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    if r["status"] not in ("DRAFT", "SUSPENDED"):
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route must be DRAFT or SUSPENDED to activate")
    if r["status"] == "DRAFT":
        has_active_store = any(
            s["route_id"] == r["id"] and s["status"] == "ACTIVE"
            for s in DB.stores.values()
        )
        if not has_active_store:
            raise err(
                ERR_ROUTE_NOT_ACTIVE,
                "Route has no ACTIVE store; a draft route is not ready to activate",
            )
    apply_changes(r, {"status": "ACTIVE"})
    return success_object(serialize_route(r))


@bp.post("/dairy/routes/<routeId>/suspend")
def suspend_route(routeId):
    require_role("TerritoryManager")
    r = DB.routes.get(routeId)
    if r is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    if r["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route must be ACTIVE to suspend")
    apply_changes(r, {"status": "SUSPENDED"})
    return success_object(serialize_route(r))


@bp.post("/dairy/routes/<routeId>/retire")
def retire_route(routeId):
    require_role("TerritoryManager")
    r = DB.routes.get(routeId)
    if r is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    if r["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route must be ACTIVE or SUSPENDED to retire")
    route_store_ids = {s["id"] for s in DB.stores.values() if s["route_id"] == r["id"]}
    open_orders = any(
        o["store_id"] in route_store_ids
        and o["fulfillment_status"] in ("PLANNED", "CONFIRMED")
        for o in DB.orders.values()
    )
    if open_orders:
        raise err(ERR_ROUTE_HAS_OPEN_ORDERS, "Route has orders in PLANNED or CONFIRMED")
    open_listing = any(
        l["route_id"] == r["id"] and l["status"] in OPEN_LISTING_STATES
        for l in DB.route_sale_listings.values()
    )
    if open_listing:
        raise err(ERR_ROUTE_HAS_OPEN_ORDERS, "Route has an open sale listing")
    # Cascade: ACTIVE stores -> INACTIVE; their PLANNED orders -> CANCELLED
    # (unreachable given the precondition, but implemented per spec); each
    # affected trip's reserved load is recomputed.
    r["status"] = "RETIRED"
    touch(r)
    affected_trips = set()
    for s in DB.stores.values():
        if s["route_id"] == r["id"] and s["status"] == "ACTIVE":
            s["status"] = "INACTIVE"
            touch(s)
    for o in DB.orders.values():
        if o["store_id"] in route_store_ids and o["fulfillment_status"] == "PLANNED":
            o["fulfillment_status"] = "CANCELLED"
            touch(o)
            affected_trips.add(o["trip_id"])
    for tid in affected_trips:
        t = DB.trips.get(tid)
        if t is not None:
            refresh_trip_loaded_cases(t)
    return success_object(serialize_route(r))
