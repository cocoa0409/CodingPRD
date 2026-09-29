from decimal import Decimal

from flask import Blueprint

import auth
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("orders", __name__)
ZERO = Decimal("0")
WRAP_SPECS = ["KRAFT_ONLY", "POLY_COATED", "STRETCH_HOOD"]


@bp.post("/customer-orders")
def create_order():
    auth.require_roles("Customer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    customer_id = shape.get_str(data, "customer_id")
    auth.own_customer_or_403(customer_id)
    product = shape.get_str(data, "product_code")
    ordered = shape.get_num(data, "ordered_tons", exclusive_min=0, maximum=2000, places=2)
    ship_date = shape.get_dt(data, "requested_ship_date")
    width = shape.get_int(data, "roll_width_mm", minimum=400, maximum=2800)
    diameter = shape.get_int(data, "roll_diameter_mm", minimum=800, maximum=1800)
    wrap = shape.get_enum(data, "wrap_spec", WRAP_SPECS)
    customer = store.get("customers", customer_id)
    if customer is None:
        raise err("ERR_PARTY_NOT_FOUND", "customer_id does not resolve")
    common.need_spec(product)
    if (width > int(customer["max_roll_width_mm"])
            or diameter > int(customer["max_roll_diameter_mm"])
            or wrap != customer["wrap_spec"]):
        raise err("ERR_CUSTOMER_SPEC_VIOLATION", "roll specification exceeds the customer's envelope")
    if customer["status"] != "ACTIVE":
        raise err("ERR_ORDER_INVALID_STATE", "customer is SUSPENDED")
    row = {
        "customer_id": customer_id,
        "product_code": product,
        "ordered_tons": ordered,
        "requested_ship_date": shape.iso(ship_date),
        "roll_width_mm": width,
        "roll_diameter_mm": diameter,
        "wrap_spec": wrap,
        "allocated_tons": float(q(ZERO, 3)),
        "shipped_tons": float(q(ZERO, 3)),
        "shortfall_tons": float(q(D(ordered), 3)),
        "scheduled_run_id": None,
        "deschedule_count": 0,
        "status": "SUBMITTED",
    }
    store.insert("customer_orders", row)
    return response.ok(common.view(row), 201)


def _need_order(oid):
    order = common.need("customer_orders", oid, "ERR_ORDER_NOT_FOUND")
    auth.own_customer_or_403(order["customer_id"])
    return order


@bp.get("/customer-orders/<oid>")
def get_order(oid):
    auth.require_roles("Customer", "MillPlanner")
    return response.ok(common.view(_need_order(oid)))


@bp.get("/customer-orders")
def list_orders():
    auth.require_roles("Customer", "MillPlanner")
    limit, offset = shape.pagination()
    rows = common.filtered("customer_orders", {
        "customer_id": "customer_id",
        "scheduled_run_id": "scheduled_run_id",
        "product_code": "product_code",
        "status": "status",
    })
    rows = common.scope_customer(rows)
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/customer-orders/<oid>/schedule")
def schedule_order(oid):
    auth.require_roles("MillPlanner")
    order = _need_order(oid)
    data = shape.body()
    run_id = shape.get_str(data, "run_id")
    expected = shape.get_version(data, "expected_order_version")
    run = store.get("production_runs", run_id)
    if run is None:
        raise err("ERR_LINK_TARGET_NOT_FOUND", "run_id does not resolve")
    if order["status"] != "SUBMITTED":
        raise err("ERR_ORDER_INVALID_STATE", "order is not SUBMITTED")
    customer = store.get("customers", order["customer_id"])
    if customer["status"] != "ACTIVE":
        raise err("ERR_ORDER_INVALID_STATE", "customer is SUSPENDED")
    if run["run_status"] != "SCHEDULED":
        raise err("ERR_RUN_INVALID_STATE", "target run is not SCHEDULED")
    if expected != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "expected_order_version is stale")
    if run["product_code"] != order["product_code"]:
        raise err("ERR_PRODUCT_MISMATCH", "order product differs from the run's product")
    booked = ZERO
    for o in store.all_rows("customer_orders"):
        if o["id"] != order["id"] and o.get("scheduled_run_id") == run["id"]:
            booked += D(o["ordered_tons"])
    if booked + D(order["ordered_tons"]) > D(run["pulp_draw_tons"]):
        raise err("ERR_RUN_CAPACITY_EXCEEDED", "run capacity exceeded")
    order["scheduled_run_id"] = run["id"]
    order["status"] = "SCHEDULED"
    store.touch("customer_orders", order)
    return response.ok(common.view(order))


@bp.post("/customer-orders/<oid>/deschedule")
def deschedule_order(oid):
    auth.require_roles("MillPlanner")
    order = _need_order(oid)
    shape.reject_unexpected_version(shape.body())
    if order["status"] != "SCHEDULED":
        raise err("ERR_ORDER_INVALID_STATE", "order is not SCHEDULED")
    if int(order["deschedule_count"]) >= 3:
        raise err("ERR_DESCHEDULE_LIMIT", "deschedule limit reached")
    order["scheduled_run_id"] = None
    order["deschedule_count"] = int(order["deschedule_count"]) + 1
    order["status"] = "SUBMITTED"
    store.touch("customer_orders", order)
    return response.ok(common.view(order))


@bp.post("/customer-orders/<oid>/ship")
def ship_order(oid):
    auth.require_roles("MillPlanner")
    order = _need_order(oid)
    shape.reject_unexpected_version(shape.body())
    if order["status"] != "ALLOCATED":
        raise err("ERR_ORDER_INVALID_STATE", "order is not ALLOCATED")
    sets = common.order_roll_sets(order["id"])
    for rs in sets:
        if rs["status"] != "ALLOCATED":
            raise err("ERR_ROLL_SET_INVALID_STATE", "every roll set of the order must be ALLOCATED")
    run = store.get("production_runs", order.get("scheduled_run_id")) \
        if order.get("scheduled_run_id") else None
    if run is None or run["quality_status"] != "CERTIFIED":
        raise err("ERR_RUN_NOT_CERTIFIED", "the order's scheduled run is not CERTIFIED")
    for rs in sets:
        rs["status"] = "SHIPPED"
        store.touch("roll_sets", rs)
    order["status"] = "SHIPPED"
    common.recompute_order_ledger(order)
    store.touch("customer_orders", order)
    return response.ok(common.view(order))


@bp.post("/customer-orders/<oid>/short-close")
def short_close_order(oid):
    auth.require_roles("MillPlanner")
    order = _need_order(oid)
    shape.reject_unexpected_version(shape.body())
    if order["status"] != "PARTIALLY_ALLOCATED":
        raise err("ERR_ORDER_INVALID_STATE", "order is not PARTIALLY_ALLOCATED")
    if D(order["shortfall_tons"]) <= ZERO:
        raise err("ERR_NO_SHORTFALL", "order has no outstanding shortfall")
    frozen = order["shortfall_tons"]
    for rs in common.order_roll_sets(order["id"]):
        if rs["status"] == "ALLOCATED":
            rs["status"] = "SHIPPED"
            store.touch("roll_sets", rs)
    order["status"] = "SHORT_CLOSED"
    common.recompute_order_ledger(order)
    order["shortfall_tons"] = frozen
    store.touch("customer_orders", order)
    return response.ok(common.view(order))


@bp.post("/customer-orders/<oid>/cancel")
def cancel_order(oid):
    auth.require_roles("Customer")
    order = _need_order(oid)
    shape.reject_unexpected_version(shape.body())
    if order["status"] != "SUBMITTED":
        raise err("ERR_ORDER_INVALID_STATE", "order is not SUBMITTED")
    if D(order["allocated_tons"]) != ZERO:
        raise err("ERR_TONNAGE_ALREADY_BOOKED", "order has allocated tonnage")
    order["status"] = "CANCELLED"
    store.touch("customer_orders", order)
    return response.ok(common.view(order))
