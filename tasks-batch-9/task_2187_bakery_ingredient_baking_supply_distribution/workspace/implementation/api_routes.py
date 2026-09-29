"""Delivery routes, stops, sealing, dispatch and the dock (PRD §3.9 - §3.10)."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import authenticate
from common import fk_lookup, path_lookup, unique_or_fail
from errors import fail
from store import D, lb

bp = Blueprint("routes", __name__)

ROUTE_STATES = ("PLANNING", "SEALED", "DISPATCHED", "COMPLETED", "ABORTED")
STOP_STATES = ("PLANNED", "DELIVERED", "SHORTED", "CANCELLED")
ROUTE_READ_ROLES = ("LogisticsPlanner", "WarehouseOperator", "QualityManager", "PlatformAdmin")
STOP_READ_ROLES = ("LogisticsPlanner", "WarehouseOperator", "QualityManager",
                   "CustomerBuyer", "PlatformAdmin")


def _order_pounds(order):
    total = D(0)
    for ln in calc.order_lines_of(order["id"]):
        total += D(ln["quantity_lb"])
    return total


def _assign_sequence(route):
    seq = 0
    for stop in calc.stops_of(route["id"]):
        if stop["status"] == "CANCELLED":
            continue
        seq += 1
        if stop["sequence_no"] != seq:
            stop["sequence_no"] = seq
            store.bump(stop)


def _clear_sequence(route):
    for stop in calc.stops_of(route["id"]):
        if stop["sequence_no"] != 0:
            stop["sequence_no"] = 0
            store.bump(stop)


# --------------------------------------------------------------- routes ----
@bp.post("/routes")
def create_route():
    authenticate(("LogisticsPlanner",))
    body = v.body()
    route_code = v.string(body, "route_code", min_len=2, max_len=16)
    service_on = v.date(body, "service_on")
    capacity = v.number(body, "vehicle_capacity_lb", minimum=1000)
    buffer_minutes = v.integer(body, "service_buffer_minutes", required=False,
                               minimum=0, default=30)
    unique_or_fail("routes", "route_code", route_code)
    rec = store.base_record()
    rec.update({
        "route_code": route_code,
        "service_on": service_on,
        "vehicle_capacity_lb": lb(capacity),
        "allergen_class_lock": "NONE",
        "service_buffer_minutes": buffer_minutes,
        "status": "PLANNING",
        "planned_load_lb": D("0.00"),
        "utilization_pct": D("0.00"),
        "stop_count": 0,
    })
    store.insert("routes", rec)
    return envelope.created(serialize.route(rec))


@bp.get("/routes/<rid>")
def read_route(rid):
    authenticate(ROUTE_READ_ROLES)
    return envelope.ok(serialize.route(path_lookup("routes", rid)))


@bp.get("/routes")
def list_routes():
    authenticate(ROUTE_READ_ROLES)
    limit, offset = v.pagination()
    service_on = v.q_date("service_on")
    status = v.q_enum("status", ROUTE_STATES)
    rows = [r for r in store.all_of("routes")
            if (service_on is None or store.day_of(r["service_on"]) == service_on)
            and (status is None or r["status"] == status)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.route)
    return envelope.listing(data, limit, offset, total)


# ---------------------------------------------------------------- stops ----
def _check_allergen_lock(route, order):
    classes = domain.order_allergen_classes(order)
    if route["allergen_class_lock"] != "NONE":
        if any(c != route["allergen_class_lock"] for c in classes):
            fail("ERR_ROUTE_ALLERGEN_LOCK_CONFLICT",
                 "The trailer is locked to allergen class %s"
                 % route["allergen_class_lock"])
        return route["allergen_class_lock"]
    non_none = sorted(c for c in classes if c != "NONE")
    if len(non_none) > 1:
        fail("ERR_ROUTE_ALLERGEN_LOCK_CONFLICT",
             "A trailer may never hold two different allergen classes at once")
    return non_none[0] if non_none else "NONE"


def _check_stop_windows(route, new_start, new_end, skip_id=None):
    buffer_delta = timedelta(minutes=route["service_buffer_minutes"])
    for stop in calc.stops_of(route["id"]):
        if stop["status"] == "CANCELLED" or stop["id"] == skip_id:
            continue
        ex_start = stop["window_start_at"]
        ex_end = stop["window_end_at"]
        if new_start < ex_end and ex_start < new_end:
            fail("ERR_STOP_WINDOW_CONFLICT",
                 "The delivery window overlaps stop %s" % stop["id"])
        gap = (new_start - ex_end) if new_start >= ex_end else (ex_start - new_end)
        if gap < buffer_delta:
            fail("ERR_STOP_WINDOW_CONFLICT",
                 "Stops must be separated by at least %d minutes"
                 % route["service_buffer_minutes"])


def _check_silo_windows(order, new_start, new_end):
    if order["delivery_mode"] != "BULK":
        return
    for ln in calc.order_lines_of(order["id"]):
        silo = store.get("silos", ln["silo_id"]) if ln["silo_id"] else None
        if silo is None:
            silo = calc.find_silo(order["customer_id"], ln["product_id"])
        if silo is None:
            continue
        fs = silo["last_fill_window_start_at"]
        fe = silo["last_fill_window_end_at"]
        if fs is None or fe is None:
            continue
        if new_start <= fe and fs <= new_end:
            fail("ERR_SILO_FILL_WINDOW_CONFLICT",
                 "The stop window collides with silo %s's accepted fill window"
                 % silo["silo_code"])


def _check_route_day(route, new_start, new_end):
    day_start = store.day_of(route["service_on"])
    day_end = day_start + timedelta(days=1)
    if not (day_start <= new_start < day_end and day_start < new_end <= day_end):
        fail("ERR_ROUTE_DATE_MISMATCH",
             "The delivery window must fall inside the route's service day")


@bp.post("/routes/<rid>/stops")
def create_stop(rid):
    authenticate(("LogisticsPlanner",))
    body = v.body()
    order_id = v.string(body, "order_id", min_len=1)
    window_start = v.instant(body, "window_start_at", required=True)
    window_end = v.instant(body, "window_end_at", required=True)
    expected_version = v.integer(body, "expected_route_version", minimum=0)
    route = path_lookup("routes", rid)
    order = fk_lookup("orders", order_id)
    if route["version"] != expected_version:
        fail("ERR_STALE_ROUTE_VERSION",
             "expected_route_version %s does not match the current route version"
             % expected_version)
    if route["status"] != "PLANNING":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "A route in %s cannot take further stops" % route["status"])
    if order["fulfillment_status"] != "ALLOCATED":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "Only an ALLOCATED order may be added to a route")
    new_lock = _check_allergen_lock(route, order)
    _check_stop_windows(route, window_start, window_end)
    _check_silo_windows(order, window_start, window_end)
    _check_route_day(route, window_start, window_end)

    candidate = {
        "route_id": route["id"],
        "order_id": order["id"],
        "window_start_at": window_start,
        "window_end_at": window_end,
        "created_at": store.now(),
        "_seq": store.peek_seq(),
        "status": "PLANNED",
    }
    participating = [s for s in calc.stops_of(route["id"]) if s["status"] != "CANCELLED"]
    participating.append(candidate)
    participating.sort(key=lambda s: (s["window_start_at"], s["created_at"], s["_seq"]))
    calc.route_waterfall(route, participating=participating, enforce=True)

    rec = store.base_record()
    rec.update({
        "route_id": route["id"],
        "order_id": order["id"],
        "window_start_at": window_start,
        "window_end_at": window_end,
        "sequence_no": 0,
        "status": "PLANNED",
        "delivered_lb": D("0.00"),
    })
    store.insert("stops", rec)
    order["fulfillment_status"] = "ROUTED"
    store.bump(order)
    route["allergen_class_lock"] = new_lock
    calc.apply_waterfall(route, enforce=False)
    store.bump(route)
    return envelope.created(serialize.route_stop(rec))


@bp.get("/routes/<rid>/stops")
def list_stops_of(rid):
    authenticate(STOP_READ_ROLES)
    limit, offset = v.pagination()
    route = path_lookup("routes", rid)
    rows = calc.stops_of(route["id"])
    data, total = v.page(rows, limit, offset, serialize.route_stop)
    return envelope.listing(data, limit, offset, total)


@bp.get("/route-stops")
def list_stops():
    authenticate(STOP_READ_ROLES)
    limit, offset = v.pagination()
    route_id = v.q_str("route_id")
    order_id = v.q_str("order_id")
    status = v.q_enum("status", STOP_STATES)
    rows = [s for s in store.all_of("stops")
            if (route_id is None or s["route_id"] == route_id)
            and (order_id is None or s["order_id"] == order_id)
            and (status is None or s["status"] == status)]
    rows.sort(key=lambda s: (s["window_start_at"], s["created_at"], s["_seq"]))
    data, total = v.page(rows, limit, offset, serialize.route_stop)
    return envelope.listing(data, limit, offset, total)


@bp.get("/route-stops/<sid>")
def read_stop(sid):
    authenticate(STOP_READ_ROLES)
    return envelope.ok(serialize.route_stop(path_lookup("stops", sid)))


@bp.delete("/route-stops/<sid>")
def cancel_stop(sid):
    authenticate(("LogisticsPlanner",))
    stop = path_lookup("stops", sid)
    if stop["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A stop in %s cannot be cancelled" % stop["status"])
    route = store.get("routes", stop["route_id"])
    if route is None or route["status"] not in ("PLANNING", "SEALED"):
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "Stops may only be cancelled while the route is PLANNING or SEALED")
    was_sealed = route["status"] == "SEALED"
    stop["status"] = "CANCELLED"
    stop["sequence_no"] = 0
    store.bump(stop)
    order = store.get("orders", stop["order_id"])
    if order is not None and order["fulfillment_status"] == "ROUTED":
        order["fulfillment_status"] = "ALLOCATED"
        store.bump(order)
    calc.apply_waterfall(route, enforce=False)
    if route["stop_count"] == 0 and was_sealed:
        route["status"] = "PLANNING"
        route["allergen_class_lock"] = "NONE"
        _clear_sequence(route)
    store.bump(route)
    return envelope.ok(serialize.route_stop(stop))


# ------------------------------------------------------- seal / dispatch ----
@bp.post("/routes/<rid>/seal")
def seal_route(rid):
    authenticate(("LogisticsPlanner",))
    v.body()
    route = path_lookup("routes", rid)
    if route["status"] != "PLANNING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A route in %s cannot be sealed" % route["status"])
    participating = [s for s in calc.stops_of(route["id"]) if s["status"] != "CANCELLED"]
    if not participating:
        fail("ERR_INVALID_STATE_TRANSITION", "A route needs at least one stop to seal")
    orders = []
    for stop in participating:
        order = store.get("orders", stop["order_id"])
        if order is None or order["fulfillment_status"] != "ROUTED":
            fail("ERR_RELATED_ENTITY_STATE_INVALID",
                 "Every stop's order must be ROUTED to seal the load plan")
        orders.append(order)
    for order in orders:
        classes = domain.order_allergen_classes(order)
        if order["delivery_mode"] == "BULK":
            if any(c != route["allergen_class_lock"] for c in classes):
                fail("ERR_ROUTE_ALLERGEN_LOCK_CONFLICT",
                     "A bulk stop's allergen class must equal the trailer lock")
        elif route["allergen_class_lock"] != "NONE":
            if any(c != route["allergen_class_lock"] for c in classes):
                fail("ERR_ROUTE_ALLERGEN_LOCK_CONFLICT",
                     "The trailer is locked to allergen class %s"
                     % route["allergen_class_lock"])
    count, load, util = calc.route_waterfall(route, participating=participating, enforce=True)
    if util > D("100"):
        fail("ERR_ROUTE_CAPACITY_EXCEEDED", "Route utilization exceeds 100%")
    for order in orders:
        customer = store.get("customers", order["customer_id"])
        if customer is not None and order["total_cents"] < customer["min_drop_cents"]:
            fail("ERR_MIN_DROP_NOT_MET",
                 "Order %s does not reach the bakery minimum drop" % order["id"])
    route["stop_count"] = count
    route["planned_load_lb"] = load
    route["utilization_pct"] = util
    route["status"] = "SEALED"
    _assign_sequence(route)
    store.bump(route)
    return envelope.ok(serialize.route(route))


@bp.post("/routes/<rid>/unseal")
def unseal_route(rid):
    authenticate(("LogisticsPlanner",))
    v.body()
    route = path_lookup("routes", rid)
    if route["status"] != "SEALED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A route in %s cannot be unsealed" % route["status"])
    route["status"] = "PLANNING"
    _clear_sequence(route)
    store.bump(route)
    return envelope.ok(serialize.route(route))


@bp.post("/routes/<rid>/dispatch")
def dispatch_route(rid):
    authenticate(("LogisticsPlanner",))
    v.body()
    route = path_lookup("routes", rid)
    if route["status"] != "SEALED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A route in %s cannot be dispatched" % route["status"])
    if store.clock_date() != store.day_of(route["service_on"]):
        fail("ERR_ROUTE_DATE_MISMATCH",
             "A route may only be dispatched on its service date")
    participating = [s for s in calc.stops_of(route["id"]) if s["status"] == "PLANNED"]
    orders = []
    for stop in participating:
        order = store.get("orders", stop["order_id"])
        if order is None or order["pricing_status"] not in ("PROVISIONAL", "FINAL"):
            fail("ERR_RELATED_ENTITY_STATE_INVALID",
                 "Every stop's order must be priced before dispatch")
        orders.append(order)
    for order in orders:
        if order["fulfillment_status"] == "ROUTED":
            order["fulfillment_status"] = "LOADED"
            store.bump(order)
    route["status"] = "DISPATCHED"
    store.bump(route)
    return envelope.ok(serialize.route(route))


@bp.post("/routes/<rid>/abort")
def abort_route(rid):
    authenticate(("LogisticsPlanner",))
    body = v.body()
    v.string(body, "abort_reason", min_len=1, max_len=200)
    route = path_lookup("routes", rid)
    if route["status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A route in %s cannot be aborted" % route["status"])
    stops = calc.stops_of(route["id"])
    if any(s["status"] in ("DELIVERED", "SHORTED") for s in stops):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A route with a completed drop cannot be aborted")
    for stop in stops:
        if stop["status"] != "PLANNED":
            continue
        stop["status"] = "CANCELLED"
        stop["sequence_no"] = 0
        store.bump(stop)
        order = store.get("orders", stop["order_id"])
        if order is not None and order["fulfillment_status"] == "LOADED":
            order["fulfillment_status"] = "ALLOCATED"
            store.bump(order)
    route["status"] = "ABORTED"
    route["stop_count"] = 0
    route["planned_load_lb"] = D("0.00")
    route["utilization_pct"] = D("0.00")
    store.bump(route)
    return envelope.ok(serialize.route(route))


# ------------------------------------------------------------- the dock ----
def _dock_preconditions(stop):
    if stop["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A stop in %s cannot be confirmed" % stop["status"])
    route = store.get("routes", stop["route_id"])
    if route is None or route["status"] != "DISPATCHED":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "Drops may only be confirmed on a DISPATCHED route")
    order = store.get("orders", stop["order_id"])
    if order is None or order["fulfillment_status"] != "LOADED":
        fail("ERR_RELATED_ENTITY_STATE_INVALID",
             "The stop's order must be LOADED to confirm a drop")
    return route, order


@bp.post("/route-stops/<sid>/deliver")
def deliver_stop(sid):
    authenticate(("WarehouseOperator",))
    v.body()
    stop = path_lookup("stops", sid)
    route, order = _dock_preconditions(stop)
    zones = {}
    lots = []
    for ln in calc.order_lines_of(order["id"]):
        qty = D(ln["quantity_lb"])
        lot = store.get("lots", ln["lot_id"]) if ln["lot_id"] else None
        if lot is not None:
            lot["quantity_reserved_lb"] = lb(D(lot["quantity_reserved_lb"]) - qty)
            lot["quantity_consumed_lb"] = lb(D(lot["quantity_consumed_lb"]) + qty)
            store.bump(lot)
            zones[lot["zone_id"]] = store.get("zones", lot["zone_id"])
            lots.append(lot)
        silo = store.get("silos", ln["silo_id"]) if ln["silo_id"] else None
        if silo is not None:
            silo["residual_lb"] = lb(D(silo["residual_lb"]) + qty)
            silo["last_fill_window_start_at"] = stop["window_start_at"]
            silo["last_fill_window_end_at"] = stop["window_end_at"]
            store.bump(silo)
        ln["allocation_status"] = "SHIPPED"
        store.bump(ln)
    stop["status"] = "DELIVERED"
    stop["delivered_lb"] = lb(_order_pounds(order))
    store.bump(stop)
    order["fulfillment_status"] = "DELIVERED"
    order["delivered_on"] = store.clock_date()
    store.bump(order)
    for zone in zones.values():
        calc.recompute_zone_on_hand(zone)
    for lot in lots:
        domain.maybe_deplete_lot(lot)
    calc.recompute_risk_score(store.get("customers", order["customer_id"]),
                              "audited_closed_book")
    domain.maybe_complete_route(route)
    return envelope.ok(serialize.route_stop(stop))


@bp.post("/route-stops/<sid>/short")
def short_stop(sid):
    authenticate(("WarehouseOperator",))
    body = v.body()
    delivered_total = v.number(body, "delivered_lb_total", minimum=0)
    v.string(body, "short_reason", min_len=1, max_len=200)
    stop = path_lookup("stops", sid)
    route, order = _dock_preconditions(stop)
    requested = _order_pounds(order)
    if not (D(0) < D(delivered_total) < requested):
        fail("ERR_SHORT_QUANTITY_INVALID",
             "delivered_lb_total must be strictly between 0 and %s" % requested)
    remaining = D(delivered_total)
    zones = {}
    lots = []
    shorted_by_line = {}
    for ln in calc.order_lines_of(order["id"]):
        qty = D(ln["quantity_lb"])
        taken = min(remaining, qty)
        remaining -= taken
        shorted = qty - taken
        shorted_by_line[ln["id"]] = shorted
        lot = store.get("lots", ln["lot_id"]) if ln["lot_id"] else None
        if lot is not None:
            lot["quantity_reserved_lb"] = lb(D(lot["quantity_reserved_lb"]) - qty)
            lot["quantity_consumed_lb"] = lb(D(lot["quantity_consumed_lb"]) + taken)
            lot["quantity_on_hand_lb"] = lb(D(lot["quantity_on_hand_lb"]) + shorted)
            store.bump(lot)
            zones[lot["zone_id"]] = store.get("zones", lot["zone_id"])
            lots.append(lot)
        silo = store.get("silos", ln["silo_id"]) if ln["silo_id"] else None
        if silo is not None and taken > 0:
            silo["residual_lb"] = lb(D(silo["residual_lb"]) + taken)
            silo["last_fill_window_start_at"] = stop["window_start_at"]
            silo["last_fill_window_end_at"] = stop["window_end_at"]
            store.bump(silo)
        ln["allocation_status"] = "SHIPPED"
        store.bump(ln)
    stop["status"] = "SHORTED"
    stop["delivered_lb"] = lb(delivered_total)
    store.bump(stop)
    order["fulfillment_status"] = "SHORT_SHIPPED"
    order["short_ship_lb"] = lb(requested - D(delivered_total))
    order["delivered_on"] = store.clock_date()
    store.bump(order)
    domain.return_contract_volume(order, pounds_by_line=shorted_by_line)
    for zone in zones.values():
        calc.recompute_zone_on_hand(zone)
    for lot in lots:
        domain.maybe_deplete_lot(lot)
    calc.recompute_risk_score(store.get("customers", order["customer_id"]),
                              "audited_closed_book")
    domain.maybe_complete_route(route)
    return envelope.ok(serialize.route_stop(stop))
