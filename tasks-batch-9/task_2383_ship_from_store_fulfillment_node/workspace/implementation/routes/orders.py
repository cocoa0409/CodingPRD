"""Customer orders, demand lines and the cost-comparison read."""
from flask import Blueprint

from constants import (
    API_PREFIX, CANCEL_REASONS, FULFILLMENT_STATUSES, LINE_STATUSES, LIVE_STATUSES,
    ROLE_ASSOCIATE, ROLE_CARE, ROLE_CARRIER, ROLE_PLANNER, ROUTING_STATUSES,
    SERVICE_LEVELS,
)
from db import all_of, db, new_row, sorted_rows
from errors import ApiError
from middleware import (
    authenticate, body, get_dt, get_enum, get_int, get_str, pagination_args,
    query_enum, query_str,
)
from response import object_response
from routes.common import apply_filter, fetch, finish, listing, show
from services import notifications
from services.assignments import release_assignment
from services.costs import dc_baseline_cents
from services.derive import (
    assignments_of_order, order_cost, order_lines_of, recompute_all,
)

bp = Blueprint("orders", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


@bp.route(API_PREFIX + "/orders", methods=["POST"])
def create_order():
    authenticate(ROLE_CARE)
    payload = body()
    order_code = get_str(payload, "order_code")
    customer_ref = get_str(payload, "customer_ref")
    destination_zone = get_int(payload, "destination_zone", minimum=1, maximum=8)
    service_level = get_enum(payload, "service_level", SERVICE_LEVELS)
    promised_ship_by = get_dt(payload, "promised_ship_by_utc")

    if any(o["order_code"] == order_code for o in db.orders.values()):
        raise ApiError("ERR_DUPLICATE_ORDER_CODE")

    order = new_row("orders", {
        "order_code": order_code,
        "customer_ref": customer_ref,
        "destination_zone": destination_zone,
        "service_level": service_level,
        "promised_ship_by_utc": promised_ship_by,
        "routing_status": "UNROUTED",
        "fulfillment_status": "PENDING",
        "total_units": 0,
        "shipped_units": 0,
        "unassigned_units": 0,
        "dc_fallback_units": 0,
        "split_count": 0,
        "reroute_attempt_count": 0,
        "provisional_cost_cents": 0,
        "final_cost_cents": None,
        "cost_variance_cents": None,
        "dc_baseline_cost_cents": dc_baseline_cents(destination_zone, 0),
        "cost_index_bps": 0,
    })
    return finish(order, 201)


@bp.route(API_PREFIX + "/orders", methods=["GET"])
def list_orders():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("orders")
    rows = apply_filter(rows, "routing_status",
                        query_enum("routing_status", ROUTING_STATUSES))
    rows = apply_filter(rows, "fulfillment_status",
                        query_enum("fulfillment_status", FULFILLMENT_STATUSES))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authenticate(*ANY_ROLE)
    return show(fetch("orders", order_id))


@bp.route(API_PREFIX + "/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    authenticate(ROLE_CARE)
    payload = body()
    sku_id = get_str(payload, "sku_id")
    quantity = get_int(payload, "quantity", minimum=1)
    unit_price_cents = get_int(payload, "unit_price_cents", minimum=0)

    order = fetch("orders", order_id)
    fetch("skus", sku_id)
    if order["routing_status"] != "UNROUTED":
        raise ApiError("ERR_ORDER_LINES_LOCKED")

    line = new_row("order_lines", {
        "order_id": order_id,
        "sku_id": sku_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "assigned_units": 0,
        "shipped_units": 0,
        "cancelled_units": 0,
        "dc_fallback_units": 0,
        "open_units": quantity,
        "line_status": "OPEN",
    })
    return finish(line, 201, explicit=[order])


@bp.route(API_PREFIX + "/order-lines", methods=["GET"])
def list_order_lines():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("order_lines")
    rows = apply_filter(rows, "order_id", query_str("order_id"))
    rows = apply_filter(rows, "sku_id", query_str("sku_id"))
    rows = apply_filter(rows, "line_status", query_enum("line_status", LINE_STATUSES))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/order-lines/<order_line_id>", methods=["GET"])
def read_order_line(order_line_id):
    authenticate(*ANY_ROLE)
    return show(fetch("order_lines", order_line_id))


@bp.route(API_PREFIX + "/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    authenticate(ROLE_CARE)
    payload = body()
    get_enum(payload, "cancel_reason_code", CANCEL_REASONS)

    order = fetch("orders", order_id)
    if order["fulfillment_status"] != "PENDING" or order["shipped_units"] != 0:
        raise ApiError("ERR_ORDER_ALREADY_SHIPPED_UNITS")

    moved = 0
    marked = []
    for assignment in sorted_rows(assignments_of_order(order_id)):
        if assignment["status"] in LIVE_STATUSES:
            moved += release_assignment(assignment, "CANCELLED", "CUSTOMER_REQUEST",
                                        to_cancelled_units=True)
            marked.append(assignment)
    recompute_all()
    for line in order_lines_of(order_id):
        if line["open_units"] > 0:
            moved += line["open_units"]
            line["cancelled_units"] = line["cancelled_units"] + line["open_units"]
    order["_cancelled"] = True
    recompute_all()

    cancelled_total = sum(l["cancelled_units"] for l in order_lines_of(order_id))
    notification_type = notifications.choose_type(
        "order_cancel", cancelled_units=cancelled_total,
        total_units=order["total_units"])
    notifications.emit(order, None, notification_type, moved)
    return finish(order, 200, explicit=[order] + marked)


@bp.route(API_PREFIX + "/orders/<order_id>/cost-comparison", methods=["GET"])
def cost_comparison(order_id):
    authenticate(ROLE_PLANNER, ROLE_CARE)
    order = fetch("orders", order_id)
    variant = "final" if order["fulfillment_status"] == "SHIPPED" else "provisional"
    breakdown = order_cost(order, variant)
    payload = {"order_id": order["id"]}
    payload.update(breakdown)
    return object_response(payload)
