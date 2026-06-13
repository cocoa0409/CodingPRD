"""Order endpoints: create, lines, confirm, cancel, invoice, pay, quote
(PRD §3.3, §3.4, §3.8, §3.9)."""
from flask import Blueprint, request, g

from db import store, new_common_fields, touch
from errors import err
from middleware import endpoint, require_owns_customer
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, optional_str, require_int, require_positive_int,
    parse_pagination, paginate,
)
from services import pricing
from services import lifecycle
from services.lookups import (
    get_shop, get_customer, get_order, get_order_line,
    get_garment_style, get_decoration_method,
    lines_of_order,
)

bp = Blueprint("orders", __name__)


# ---- Create order ----

@bp.route("/orders", methods=["POST"])
@endpoint("ShopManager", "Customer")
def create_order():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    get_shop(shop_id)
    customer_id = require_str(body, "customer_id")
    customer = get_customer(customer_id)
    # Customer ownership: a Customer may only create their own orders (PRD §2.1).
    require_owns_customer(customer_id)
    requested_ship_date = require_str(body, "requested_ship_date")
    from clock import parse_iso8601
    if parse_iso8601(requested_ship_date) is None:
        raise err("ERR_INVALID_REQUEST", "requested_ship_date must be ISO 8601")

    reorder_of = optional_str(body, "reorder_of_order_id", default=None)
    if reorder_of is not None:
        ref = store.orders.get(reorder_of)
        # Reorder must reference a FULFILLED order of the same customer (PRD §3.6).
        if ref is None or ref["customer_id"] != customer_id \
                or ref["fulfillment_status"] != "FULFILLED":
            raise err("ERR_INVALID_REORDER_SOURCE",
                      "reorder_of_order_id must reference a FULFILLED order of the same customer")

    order = new_common_fields()
    order.update({
        "shop_id": shop_id,
        "customer_id": customer_id,
        "reorder_of_order_id": reorder_of,
        "requested_ship_date": requested_ship_date,
        "is_rush": None,
        "fulfillment_status": "DRAFT",
        "billing_status": "UNBILLED",
        "deposit_paid_cents": 0,
        "final_total_cents": None,
    })
    store.orders[order["id"]] = order
    return success(view(order), status=201)


@bp.route("/orders/<order_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_order_route(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    return success(view(order), status=200)


@bp.route("/orders", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_orders():
    limit, offset = parse_pagination()
    items = list(store.orders.values())
    for key in ("shop_id", "customer_id", "reorder_of_order_id",
                "fulfillment_status", "billing_status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    # A Customer reading the list sees only their own orders (PRD §2.1).
    if g.get("user_role") == "Customer":
        items = [o for o in items if o["customer_id"] == g.get("user_id")]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---- Order lines ----

@bp.route("/orders/<order_id>/lines", methods=["POST"])
@endpoint("ShopManager", "Customer")
def add_line(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    body = get_body()
    garment_style_id = require_str(body, "garment_style_id")
    style = get_garment_style(garment_style_id)
    decoration_method_id = require_str(body, "decoration_method_id")
    method = get_decoration_method(decoration_method_id)

    color = require_str(body, "color")
    num_locations = require_int(body, "num_locations")
    num_colors = require_int(body, "num_colors", default=1)
    stitch_count = require_int(body, "stitch_count", default=0)
    size_run = body.get("size_run")

    # Body well-formedness (PRD §3.3) — ERR_INVALID_REQUEST.
    if num_locations < 1:
        raise err("ERR_INVALID_REQUEST", "num_locations must be >= 1")
    if num_colors < 1:
        raise err("ERR_INVALID_REQUEST", "num_colors must be >= 1")
    if stitch_count < 0:
        raise err("ERR_INVALID_REQUEST", "stitch_count must be >= 0")
    if color not in style["available_colors"]:
        raise err("ERR_INVALID_REQUEST", "color not in style's available_colors")
    if not isinstance(size_run, dict) or not size_run:
        raise err("ERR_INVALID_REQUEST", "size_run must be a non-empty map")
    for size, qty in size_run.items():
        if size not in style["available_sizes"]:
            raise err("ERR_INVALID_REQUEST", "size not in style's available_sizes")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise err("ERR_INVALID_REQUEST", "size_run quantities must be positive integers")

    # State: lines only on a DRAFT order (PRD §3.3) — ERR_ORDER_NOT_DRAFT.
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "Lines may only be added to a DRAFT order")

    line = new_common_fields()
    line.update({
        "order_id": order_id,
        "garment_style_id": garment_style_id,
        "decoration_method_id": decoration_method_id,
        "color": color,
        "num_locations": num_locations,
        "num_colors": num_colors,
        "stitch_count": stitch_count,
        "size_run": dict(size_run),
        "line_qty": pricing.line_qty_of(size_run),
    })
    store.order_lines[line["id"]] = line
    return success(view(line), status=201)


@bp.route("/orders/<order_id>/lines", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_order_lines(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    limit, offset = parse_pagination()
    items = lines_of_order(order_id)
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.route("/order-lines/<line_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_order_line_route(line_id):
    line = get_order_line(line_id)
    order = store.orders.get(line["order_id"])
    if order is not None:
        require_owns_customer(order["customer_id"])
    return success(view(line), status=200)


@bp.route("/order-lines", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_order_lines_filtered():
    limit, offset = parse_pagination()
    items = list(store.order_lines.values())
    for key in ("order_id", "garment_style_id", "decoration_method_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    if g.get("user_role") == "Customer":
        own = {o["id"] for o in store.orders.values()
               if o["customer_id"] == g.get("user_id")}
        items = [l for l in items if l["order_id"] in own]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---- Confirm / cancel ----

@bp.route("/orders/<order_id>/confirm", methods=["POST"])
@endpoint("ShopManager")
def confirm_order_route(order_id):
    order = get_order(order_id)
    lifecycle.confirm_order(order)
    return success(view(order), status=200)


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
@endpoint("ShopManager", "Customer")
def cancel_order_route(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    lifecycle.cancel_order(order)
    return success(view(order), status=200)


# ---- Billing ----

@bp.route("/orders/<order_id>/invoice", methods=["POST"])
@endpoint("ShopManager")
def invoice_order_route(order_id):
    order = get_order(order_id)
    if order["fulfillment_status"] != "FULFILLED":
        raise err("ERR_ORDER_NOT_FULFILLED", "Order is not FULFILLED")
    if order["billing_status"] != "UNBILLED":
        raise err("ERR_ALREADY_INVOICED", "Order is already invoiced")
    lifecycle.invoice_order(order)
    return success(view(order), status=200)


@bp.route("/orders/<order_id>/pay", methods=["POST"])
@endpoint("Customer")
def pay_order_route(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    if order["billing_status"] != "INVOICED":
        raise err("ERR_NOT_INVOICED", "Order is not INVOICED")
    order["billing_status"] = "PAID"
    touch(order)
    return success(view(order), status=200)


@bp.route("/orders/<order_id>/quote", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_quote_route(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    limit, offset = parse_pagination()
    items = [q for q in store.quotes.values() if q["order_id"] == order_id]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)
