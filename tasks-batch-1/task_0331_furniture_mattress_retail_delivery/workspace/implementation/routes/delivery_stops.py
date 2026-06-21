"""DeliveryStop endpoints incl. booking guards & bubble-up (PRD §3.8, §3.9).

Booking guard order follows the PRD §3.8 narrative (PRD prose is authoritative):
  ROUTE_NOT_OPEN -> WINDOW_OUT_OF_SHIFT -> STOP_OVERLAP -> LEAD_TIME_NOT_MET
  -> ROUTE_CAPACITY_EXCEEDED, then the OCC check (expected_route_version) last
  per the validation-priority table (§1.4 p21).
"""
from flask import Blueprint

import clock
import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import calculations as calc
from services import domain, serializers

bp = Blueprint("delivery_stops", __name__)

WHITE_GLOVE_BUFFER_MINUTES = calc.WHITE_GLOVE_BUFFER_MINUTES


def _effective_end(stop_end, service_tier):
    """White-glove stops reserve a service buffer after the window."""
    if service_tier == "WHITE_GLOVE":
        return stop_end + WHITE_GLOVE_BUFFER_MINUTES
    return stop_end


@bp.post("/delivery-stops")
def book_stop():
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    body = helpers.get_body()

    # Existence (4): route then order.
    route_id = helpers.require_str(body, "route_id")
    order_id = helpers.require_str(body, "order_id")
    route = helpers.fetch(db.delivery_routes, route_id)
    order = helpers.fetch(db.orders, order_id)

    # Shape (5).
    window_start = helpers.require_int(body, "window_start_minute", minimum=0)
    window_end = helpers.require_int(body, "window_end_minute")
    if not (window_start < window_end):
        raise err("ERR_INVALID_REQUEST", "window_start_minute must be < window_end_minute.")
    expected_route_version = helpers.require_int(body, "expected_route_version")

    service_tier = order["delivery_tier"]

    # (a) Route must be OPEN (PRD §3.8, first business guard).
    if route["status"] != "OPEN":
        raise err("ERR_ROUTE_NOT_OPEN", "Route is not OPEN for booking.")

    # (b) Window must lie inside the shift; white-glove buffer must fit before shift end.
    effective_end = _effective_end(window_end, service_tier)
    if window_start < route["shift_start_minute"] or \
       window_end > route["shift_end_minute"] or \
       effective_end > route["shift_end_minute"]:
        raise err("ERR_WINDOW_OUT_OF_SHIFT", "Window falls outside the route shift.")

    # (c) Window (incl. white-glove buffer) must not overlap an active stop on the route.
    new_start = window_start
    new_end = effective_end
    for existing in domain.active_stops_for_route(route_id):
        ex_start = existing["window_start_minute"]
        ex_end = _effective_end(existing["window_end_minute"], existing["service_tier"])
        if new_start < ex_end and ex_start < new_end:
            raise err("ERR_STOP_OVERLAP", "Window overlaps an existing active stop.")

    # (d) Route service_date >= order.earliest_schedulable_date (lead time).
    esd = order.get("earliest_schedulable_date")
    if esd is not None:
        route_date = clock.parse_iso(route["service_date"]).date()
        esd_date = clock.parse_iso(esd).date()
        if route_date < esd_date:
            raise err("ERR_LEAD_TIME_NOT_MET", "Route date is before earliest schedulable date.")

    # (e) Capacity: committed_units + unit_load must not exceed capacity_units.
    unit_load = sum(ln["quantity"] for ln in domain.active_lines_for_order(order_id))
    if route["committed_units"] + unit_load > route["capacity_units"]:
        raise err("ERR_ROUTE_CAPACITY_EXCEEDED", "Booking exceeds route capacity.")

    # OCC (21, last): expected_route_version must match the live route version.
    if expected_route_version != route["version"]:
        raise err("ERR_STALE_VERSION", "Route version has advanced; re-read required.")

    stop = {
        "route_id": route_id,
        "order_id": order_id,
        "window_start_minute": window_start,
        "window_end_minute": window_end,
        "service_tier": service_tier,
        "unit_load": unit_load,
        "status": "BOOKED",
    }
    helpers.stamp_create(stop)
    db.delivery_stops[stop["id"]] = stop

    # Side effects: route committed_units += unit_load (route version bump);
    # order CONFIRMED -> SCHEDULED (order version bump).
    route["committed_units"] += unit_load
    helpers.touch(route)
    if order["fulfillment_status"] == "CONFIRMED":
        order["fulfillment_status"] = "SCHEDULED"
    helpers.touch(order)

    return response.object_response(serializers.delivery_stop(stop), status=201)


@bp.get("/delivery-stops/<sid>")
def get_stop(sid):
    user_id, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager", "SalesAssociate", "Customer"})
    stop = helpers.fetch(db.delivery_stops, sid)
    if role == "Customer":
        order = db.orders.get(stop["order_id"])
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.delivery_stop(stop))


@bp.post("/delivery-stops/<sid>/dispatch")
def dispatch_stop(sid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    stop = helpers.fetch(db.delivery_stops, sid)
    if stop["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Stop is not BOOKED.")
    route = db.delivery_routes.get(stop["route_id"])
    if route is None or route["status"] != "LOCKED":
        raise err("ERR_ROUTE_NOT_LOCKED", "Route is not LOCKED.")
    stop["status"] = "DISPATCHED"
    helpers.touch(stop)
    return response.object_response(serializers.delivery_stop(stop))


@bp.post("/delivery-stops/<sid>/complete")
def complete_stop(sid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    stop = helpers.fetch(db.delivery_stops, sid)
    if stop["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Stop is not DISPATCHED.")

    completion_time = clock.iso_now()
    stop["status"] = "COMPLETED"
    helpers.touch(stop)

    # Bubble-up: order SCHEDULED -> DELIVERED; stamp delivered_on on the order's lines;
    # decrement route committed_units.
    order = db.orders.get(stop["order_id"])
    if order is not None and order["fulfillment_status"] == "SCHEDULED":
        order["fulfillment_status"] = "DELIVERED"
        for ln in domain.lines_for_order(order["id"]):
            ln["_delivered_on"] = completion_time
        helpers.touch(order)

    route = db.delivery_routes.get(stop["route_id"])
    if route is not None:
        route["committed_units"] = max(0, route["committed_units"] - stop["unit_load"])
        helpers.touch(route)

    return response.object_response(serializers.delivery_stop(stop))


@bp.post("/delivery-stops/<sid>/cancel")
def cancel_stop(sid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    stop = helpers.fetch(db.delivery_stops, sid)
    if stop["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Stop is not BOOKED.")

    stop["status"] = "CANCELLED"
    helpers.touch(stop)

    route = db.delivery_routes.get(stop["route_id"])
    if route is not None:
        route["committed_units"] = max(0, route["committed_units"] - stop["unit_load"])
        helpers.touch(route)

    # Bubble-up: if this was the order's only active stop, SCHEDULED -> CONFIRMED.
    order = db.orders.get(stop["order_id"])
    if order is not None:
        remaining = domain.active_stops_for_order(order["id"])
        if not remaining and order["fulfillment_status"] == "SCHEDULED":
            order["fulfillment_status"] = "CONFIRMED"
        helpers.touch(order)

    return response.object_response(serializers.delivery_stop(stop))
