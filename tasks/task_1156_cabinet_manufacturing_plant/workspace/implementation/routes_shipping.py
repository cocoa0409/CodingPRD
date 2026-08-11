"""Delivery routes, consolidation, dispatch, and hold override (PRD §3.7, §3.9)."""
from flask import Blueprint, request

from auth import require_any_role, require_roles
from domain import (
    compute_freight_cents,
    live_lines,
    order_hold_status,
    price_order_final,
    release_hold,
    route_orders,
    route_reserved_cu_ft,
)
from errors import api_error
from serializers import ser_hold, ser_route
from store import db, new_id, now, stamp, touch
from util import Body, D, paginate, respond_list, respond_object, sort_records

bp = Blueprint("shipping", __name__)


def _get_route(route_id):
    route = db.routes.get(route_id)
    if route is None:
        raise api_error("ERR_ROUTE_NOT_FOUND", f"DeliveryRoute {route_id} not found")
    return route


@bp.post("/kcma/delivery-routes")
def create_delivery_route():
    require_roles({"ShippingCoordinator"})
    body = Body(request.get_json(silent=True))
    route_code = body.req_str("route_code")
    route_date = body.req_date("route_date")
    capacity_cu_ft = body.req_num("capacity_cu_ft", min_value=0, exclusive_min=True)

    # priority 11: route date must not precede the logical clock's current date
    if route_date is not None and route_date < now().date():
        raise api_error("ERR_SCHEDULE_DATE_IN_PAST", "route_date is before the current date")
    # priority 14: field sanity incl. unique code
    if route_code is not None and any(
        r["route_code"] == route_code for r in db.routes.values()
    ):
        body.add_error("ERR_DUPLICATE_CODE", f"route_code {route_code} already exists")
    body.raise_field_errors()

    route = {
        "id": new_id(),
        "route_code": route_code,
        "route_date": route_date.isoformat(),
        "capacity_cu_ft": capacity_cu_ft,
        "status": "PLANNED",
        "_next_stop_seq": 1,
    }
    stamp(route)
    db.routes[route["id"]] = route
    return respond_object(ser_route(route), 201)


@bp.get("/kcma/delivery-routes")
def list_delivery_routes():
    require_any_role()
    records = list(db.routes.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_route(r) for r in page], total, limit, offset)


@bp.post("/kcma/delivery-routes/<routeId>/assign-order")
def assign_order_to_route(routeId):
    require_roles({"ShippingCoordinator"})
    route = _get_route(routeId)                                   # priority 4
    body = Body(request.get_json(silent=True))
    order_id = body.req_str("order_id")
    expected_order_version = body.req_int("expected_order_version")
    # priority 5: body FK exists
    order = None
    if order_id is not None:
        order = db.orders.get(order_id)
        if order is None:
            raise api_error("ERR_ORDER_NOT_FOUND", f"Order {order_id} not found")
    # priority 6: route PLANNED; order in SUBMITTED/IN_PRODUCTION/READY_TO_SHIP
    if route["status"] != "PLANNED":
        raise api_error("ERR_ROUTE_NOT_PLANNED", "Assign requires the route in PLANNED")
    if order is not None and order["status"] not in (
        "SUBMITTED",
        "IN_PRODUCTION",
        "READY_TO_SHIP",
    ):
        raise api_error(
            "ERR_ORDER_NOT_ROUTE_ASSIGNABLE",
            "Order must be SUBMITTED, IN_PRODUCTION, or READY_TO_SHIP to be assigned",
        )
    # OCC (§2.8): the only version-guarded write in the platform
    if (
        order is not None
        and expected_order_version is not None
        and expected_order_version != order["version"]
    ):
        raise api_error(
            "ERR_STALE_ORDER_VERSION",
            f"expected_order_version {expected_order_version} != current order version "
            f"{order['version']}",
        )
    # priority 13: cube ceiling — supersede removes the order's prior booking
    if order is not None:
        reserved = route_reserved_cu_ft(route["id"], exclude_order_id=order["id"])
        if reserved + order["cube_ft"] > D(route["capacity_cu_ft"]):
            raise api_error(
                "ERR_ROUTE_CUBE_EXCEEDED",
                "Route reserved cube plus order cube exceeds capacity_cu_ft",
            )
    body.raise_field_errors()  # priority 14

    order["delivery_route_id"] = route["id"]  # supersedes any prior route
    order["route_stop_seq"] = route["_next_stop_seq"]
    route["_next_stop_seq"] += 1
    touch(order)
    return respond_object(ser_route(route), 200)


@bp.post("/kcma/delivery-routes/<routeId>/lock")
def lock_route(routeId):
    require_roles({"ShippingCoordinator"})
    route = _get_route(routeId)
    if route["status"] != "PLANNED":                              # priority 6
        raise api_error("ERR_ROUTE_NOT_PLANNED", "Lock requires the route in PLANNED")
    assigned = route_orders(route["id"])
    if len(assigned) < 1:                                         # priority 6
        raise api_error("ERR_ROUTE_EMPTY", "Lock requires at least one assigned order")
    # priority 7: no assigned order may be ON_HOLD
    for order in assigned:
        if order_hold_status(order["id"]) == "ON_HOLD":
            raise api_error(
                "ERR_ORDER_ON_HOLD",
                f"Assigned order {order['id']} is ON_HOLD",
            )
    route["status"] = "LOCKED"
    touch(route)
    return respond_object(ser_route(route), 200)


@bp.post("/kcma/delivery-routes/<routeId>/dispatch")
def dispatch_route(routeId):
    require_roles({"ShippingCoordinator"})
    route = _get_route(routeId)
    if route["status"] != "LOCKED":                               # priority 6
        raise api_error("ERR_ROUTE_NOT_LOCKED", "Dispatch requires the route in LOCKED")
    assigned = route_orders(route["id"])
    # priority 7: every assigned order must be READY_TO_SHIP (checked for all
    # before any mutation — dispatch is atomic)
    for order in assigned:
        if order["status"] != "READY_TO_SHIP":
            raise api_error(
                "ERR_ORDERS_NOT_READY_TO_SHIP",
                f"Assigned order {order['id']} is not READY_TO_SHIP",
            )

    # Consolidation tier is read once from the route's assigned_order_count at
    # the dispatch instant — identical for every order on the route.
    count_at_dispatch = len(assigned)
    for order in assigned:
        merch, discount, nets, mods = price_order_final(order)
        freight = compute_freight_cents(order, count_at_dispatch)
        for line in live_lines(order):
            line["mod_surcharge_cents"] = mods[line["id"]]
            line["final_net_cents"] = nets[line["id"]]
            line["status"] = "SHIPPED"  # COMPLETED -> SHIPPED
            touch(line)
        order["final_merchandise_cents"] = merch
        order["final_discount_cents"] = discount
        order["freight_cents"] = freight
        order["grand_total_cents"] = merch - discount + freight
        order["status"] = "SHIPPED"  # READY_TO_SHIP -> SHIPPED
        order["shipped_at"] = now()
        touch(order)
    route["status"] = "DISPATCHED"
    touch(route)
    return respond_object(ser_route(route), 200)


# ---------------------------------------------------------------------------
# Holds — manual release override
# ---------------------------------------------------------------------------

@bp.post("/kcma/order-holds/<holdId>/release")
def release_order_hold(holdId):
    require_roles({"PlantAdmin"})
    hold = db.holds.get(holdId)
    if hold is None:
        raise api_error("ERR_HOLD_NOT_FOUND", f"OrderHold {holdId} not found")
    if hold["status"] != "PLACED":
        raise api_error("ERR_HOLD_NOT_RELEASABLE", "Release requires the hold in PLACED")
    release_hold(hold)
    return respond_object(ser_hold(hold), 200)
