"""Orders: create, confirm, stage, pay, fulfill, cancel.

Two parallel state dimensions evolve independently:
  fulfillment_status: DRAFT -> CONFIRMED -> STAGED -> FULFILLED; CANCELLED from
                      DRAFT/CONFIRMED/STAGED
  payment_status:     UNPAID -> PAID (CASH) | UNPAID -> INVOICED -> SETTLED (NET30)
"""
from datetime import timedelta
from flask import Blueprint, g

import db
from db import store, new_common, new_id, touch, is_int
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param
from services import exposure, pricing

bp = Blueprint("orders", __name__)

_ROLES = ("CounterRep", "BranchManager")


def get_order(oid):
    order = store.orders.get(oid)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    return order


def _gas_lines(order):
    return [l for l in order["lines"]
            if store.products[l["product_id"]]["category"] in ("GAS", "SPECIALTY_GAS")]


def _hardgood_lines(order):
    return [l for l in order["lines"]
            if store.products[l["product_id"]]["category"] == "HARDGOOD"]


@bp.route("/orders", methods=["POST"])
@require_roles(*_ROLES)
def create_order():
    b = body()
    cust_id = b.get("customer_id")
    route_id = b.get("route_id")
    lines = b.get("lines")
    # Priority 3: referenced ids must exist (customer, route, line products).
    if cust_id is not None and cust_id not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    if route_id is not None and route_id not in store.delivery_routes:
        raise ApiError("ERR_NOT_FOUND", 404, "DeliveryRoute not found")
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, dict):
                pid = line.get("product_id")
                if pid is not None and pid not in store.products:
                    raise ApiError("ERR_NOT_FOUND", 404, "Product not found: %s" % pid)
    # Priority 4: shape.
    order_type = b.get("order_type")
    fulfillment = b.get("fulfillment")
    if not isinstance(cust_id, str) or not cust_id:
        raise ApiError("ERR_VALIDATION", 400, "customer_id is required")
    if order_type not in ("RETAIL", "EXCHANGE", "SPECIAL_MIX"):
        raise ApiError("ERR_VALIDATION", 400,
                       "order_type must be RETAIL, EXCHANGE or SPECIAL_MIX")
    if fulfillment not in ("WILL_CALL", "ROUTE"):
        raise ApiError("ERR_VALIDATION", 400, "fulfillment must be WILL_CALL or ROUTE")
    if fulfillment == "ROUTE" and not route_id:
        raise ApiError("ERR_VALIDATION", 400, "route_id is required for ROUTE orders")
    if fulfillment == "WILL_CALL" and route_id is not None:
        raise ApiError("ERR_VALIDATION", 400, "route_id must be null for WILL_CALL orders")
    if not isinstance(lines, list) or not lines:
        raise ApiError("ERR_VALIDATION", 400, "lines must be a non-empty array")
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("product_id"), str):
            raise ApiError("ERR_VALIDATION", 400, "each line needs a product_id")
        qty = line.get("qty")
        if not is_int(qty) or qty <= 0:
            raise ApiError("ERR_VALIDATION", 400, "each line qty must be a positive integer")
        product = store.products[line["product_id"]]
        # Line composition: EXCHANGE -> GAS only; SPECIAL_MIX -> SPECIALTY_GAS only.
        if order_type == "EXCHANGE" and product["category"] != "GAS":
            raise ApiError("ERR_VALIDATION", 400,
                           "EXCHANGE lines must reference GAS products")
        if order_type == "SPECIAL_MIX" and product["category"] != "SPECIALTY_GAS":
            raise ApiError("ERR_VALIDATION", 400,
                           "SPECIAL_MIX lines must reference SPECIALTY_GAS products")
        clean_lines.append({
            "product_id": line["product_id"],
            "qty": qty,
            "unit_price_cents": None,
            "line_total_cents": None,
        })
    # Derived at creation: units and available_date (clock date + max specialty
    # lead time; null without specialty lines).
    units = sum(l["qty"] for l in clean_lines)
    specialty_leads = [store.products[l["product_id"]]["lead_time_days"]
                       for l in clean_lines
                       if store.products[l["product_id"]]["category"] == "SPECIALTY_GAS"]
    available_date = None
    if specialty_leads:
        available_date = (db.clock_date() + timedelta(days=max(specialty_leads))).isoformat()
    order = {
        "id": new_id(),
        "customer_id": cust_id,
        "order_type": order_type,
        "fulfillment": fulfillment,
        "route_id": route_id,
        "lines": clean_lines,
        "available_date": available_date,
        "units": units,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "delivery_fee_cents": 0,
        "hazmat_fee_cents": 0,
        "total_cents": 0,
        "invoice_id": None,
    }
    new_common(order)
    store.orders[order["id"]] = order
    return created(order)


@bp.route("/orders", methods=["GET"])
@require_roles("CounterRep", "BranchManager", "RouteDriver")
def list_orders():
    rows = list(store.orders.values())
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "route_id")
    rows = filter_param(rows, "invoice_id")
    rows = filter_param(rows, "fulfillment_status")
    return list_response(rows)


@bp.route("/orders/<oid>", methods=["GET"])
@require_roles("CounterRep", "BranchManager", "RouteDriver")
def get_one_order(oid):
    return ok(get_order(oid))


@bp.route("/orders/<oid>/confirm", methods=["POST"])
@require_roles(*_ROLES)
def confirm_order(oid):
    order = get_order(oid)
    cust = store.customers[order["customer_id"]]
    # Priority 6: the order's own state must permit DRAFT -> CONFIRMED.
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT order can be confirmed")
    # Priority 8: linked entities in compatible states.
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", 409, "Customer is %s" % cust["status"])
    route = None
    if order["fulfillment"] == "ROUTE":
        route = store.delivery_routes[order["route_id"]]
        if route["status"] != "PLANNED":
            raise ApiError("ERR_ROUTE_NOT_ACCEPTING", 409,
                           "Route is not PLANNED")
    # Priority 10: stock, cylinder availability, truck capacity.
    for line in _hardgood_lines(order):
        product = store.products[line["product_id"]]
        if product["stock_on_hand"] < line["qty"]:
            raise ApiError("ERR_STOCK_INSUFFICIENT", 409,
                           "Not enough stock for product %s" % product["sku"])
    for line in _gas_lines(order):
        grade = store.products[line["product_id"]]["gas_grade"]
        full_count = sum(1 for a in store.cylinder_assets.values()
                         if a["status"] == "FULL" and a["gas_grade"] == grade)
        if full_count < line["qty"]:
            raise ApiError("ERR_CYLINDER_UNAVAILABLE", 409,
                           "Not enough FULL %s cylinders" % grade)
    if route is not None and route["reserved_units"] + order["units"] > \
            route["truck_capacity_units"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 409,
                       "Truck capacity exceeded")
    # Resolve pricing into detached line copies first; the snapshots commit to
    # the order only if every gate passes (a failed confirm leaves no trace).
    trial_lines = [dict(l) for l in order["lines"]]
    pricing.price_lines(cust, trial_lines)
    subtotal = sum(l["line_total_cents"] for l in trial_lines)
    if order["fulfillment"] == "ROUTE" and subtotal < db.FREE_DELIVERY_THRESHOLD_CENTS:
        delivery = db.DELIVERY_FEE_CENTS
    else:
        delivery = 0
    hazmat = db.HAZMAT_FEE_CENTS if any(
        store.products[l["product_id"]]["hazmat"] for l in trial_lines) else 0
    total = subtotal + delivery + hazmat
    # Priority 11: NET30 credit check — projected + total must not strictly
    # exceed the limit (equality passes).
    if cust["terms"] == "NET30":
        if exposure.projected_exposure(cust) + total > cust["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 409,
                           "Projected exposure would exceed the credit limit")
    # Commit the pricing snapshot.
    order["lines"] = trial_lines
    order["subtotal_cents"] = subtotal
    order["delivery_fee_cents"] = delivery
    order["hazmat_fee_cents"] = hazmat
    order["total_cents"] = total
    # Reserve hardgood stock, reserve route units, flip state.
    for line in _hardgood_lines(order):
        product = store.products[line["product_id"]]
        product["stock_on_hand"] -= line["qty"]
        touch(product)
    if route is not None:
        route["reserved_units"] += order["units"]
        touch(route)
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return ok(order)


@bp.route("/orders/<oid>/stage", methods=["POST"])
@require_roles(*_ROLES)
def stage_order(oid):
    order = get_order(oid)
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CONFIRMED order can be staged")
    # Specialty blends stage only once the logical clock reaches available_date.
    if order["available_date"] is not None:
        if db.clock_date() < db.parse_date(order["available_date"]):
            raise ApiError("ERR_MIX_NOT_READY", 409,
                           "Specialty mix is not ready until %s" % order["available_date"])
    order["fulfillment_status"] = "STAGED"
    touch(order)
    return ok(order)


@bp.route("/orders/<oid>/pay", methods=["POST"])
@require_roles(*_ROLES)
def pay_order(oid):
    order = get_order(oid)
    cust = store.customers[order["customer_id"]]
    b = body()
    # Priority 4: counter payment exists only for CASH customers' orders.
    if cust["terms"] != "CASH":
        raise ApiError("ERR_VALIDATION", 400,
                       "Counter payment is only available for CASH customers")
    amount = b.get("amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_VALIDATION", 400, "amount_cents must be an integer")
    # Priority 6: payment moves only while fulfillment is CONFIRMED or STAGED.
    if order["fulfillment_status"] not in ("CONFIRMED", "STAGED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order cannot be paid in state %s" % order["fulfillment_status"])
    # Priority 11: the amount must equal the order total exactly.
    if amount != order["total_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 409,
                       "amount_cents must equal total_cents exactly")
    order["payment_status"] = "PAID"
    touch(order)
    return ok(order)


@bp.route("/orders/<oid>/fulfill", methods=["POST"])
@require_roles("CounterRep", "RouteDriver", "BranchManager")
def fulfill_order(oid):
    role = g.user_role
    order = get_order(oid)
    # Priority 2 (per-action): CounterRep fulfills WILL_CALL only, RouteDriver
    # fulfills ROUTE only, BranchManager fulfills either.
    if role == "CounterRep" and order["fulfillment"] != "WILL_CALL":
        raise ApiError("ERR_FORBIDDEN", 403,
                       "CounterRep may fulfill WILL_CALL orders only")
    if role == "RouteDriver" and order["fulfillment"] != "ROUTE":
        raise ApiError("ERR_FORBIDDEN", 403,
                       "RouteDriver may fulfill ROUTE orders only")
    b = body()
    gas = _gas_lines(order)
    issued_ids = b.get("issued_asset_ids")
    returned_ids = b.get("returned_asset_ids")
    # Priority 3: supplied asset ids must exist.
    if isinstance(issued_ids, list):
        for aid in issued_ids:
            if aid not in store.cylinder_assets:
                raise ApiError("ERR_NOT_FOUND", 404, "CylinderAsset not found: %s" % aid)
    if isinstance(returned_ids, list):
        for aid in returned_ids:
            if aid not in store.cylinder_assets:
                raise ApiError("ERR_NOT_FOUND", 404, "CylinderAsset not found: %s" % aid)
    # Priority 4: shape — gas orders need issued_asset_ids; EXCHANGE also needs
    # returned_asset_ids.
    if gas and not isinstance(issued_ids, list):
        raise ApiError("ERR_VALIDATION", 400,
                       "issued_asset_ids is required for orders with gas lines")
    if order["order_type"] == "EXCHANGE" and not isinstance(returned_ids, list):
        raise ApiError("ERR_VALIDATION", 400,
                       "returned_asset_ids is required for EXCHANGE orders")
    # Priority 6: STAGED -> FULFILLED only.
    if order["fulfillment_status"] != "STAGED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a STAGED order can be fulfilled")
    issued = [store.cylinder_assets[a] for a in issued_ids] if gas else []
    returned = [store.cylinder_assets[a] for a in returned_ids] \
        if order["order_type"] == "EXCHANGE" else []
    # Priority 7: pressure-vessel safety — no RETIRED cylinder may be issued.
    if any(a["status"] == "RETIRED" for a in issued):
        raise ApiError("ERR_CYLINDER_CONDEMNED", 409,
                       "A RETIRED cylinder may not be issued")
    # Priority 8: a ROUTE order fulfills only after its route is DISPATCHED.
    if order["fulfillment"] == "ROUTE":
        route = store.delivery_routes[order["route_id"]]
        if route["status"] != "DISPATCHED":
            raise ApiError("ERR_ROUTE_NOT_DISPATCHED", 409,
                           "Route is not DISPATCHED")
    # Priority 10: issued/returned grades and counts match the gas lines.
    if gas:
        needed_qty = sum(l["qty"] for l in gas)
        line_grades = {store.products[l["product_id"]]["gas_grade"] for l in gas}
        if len(issued) != needed_qty \
                or any(a["status"] != "FULL" for a in issued) \
                or any(a["gas_grade"] not in line_grades for a in issued):
            raise ApiError("ERR_CYLINDER_GRADE_MISMATCH", 409,
                           "Issued cylinders do not match the order's gas lines")
    if order["order_type"] == "EXCHANGE":
        total_qty = sum(l["qty"] for l in order["lines"])
        issued_grades = {a["gas_grade"] for a in issued}
        if len(returned) != total_qty \
                or any(a["status"] != "OUT" for a in returned) \
                or any(a["holder_customer_id"] != order["customer_id"] for a in returned) \
                or any(a["gas_grade"] not in issued_grades for a in returned):
            raise ApiError("ERR_CYLINDER_GRADE_MISMATCH", 409,
                           "Returned cylinders do not match the issued grades")
    # Priority 11: a CASH order must be PAID before fulfillment.
    cust = store.customers[order["customer_id"]]
    if cust["terms"] == "CASH" and order["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_REQUIRED", 409,
                       "CASH orders must be paid before fulfillment")
    # Commit: asset flips.
    for a in issued:
        a["status"] = "OUT"
        a["holder_customer_id"] = order["customer_id"]
        touch(a)
    for a in returned:
        a["status"] = "EMPTY"
        a["holder_customer_id"] = None
        a["rental_agreement_id"] = None
        touch(a)
    # Route units release (FULFILLED is not in the reserving set).
    if order["fulfillment"] == "ROUTE":
        route = store.delivery_routes[order["route_id"]]
        route["reserved_units"] -= order["units"]
        touch(route)
    # NET30: post the order invoice (credit cascade hop 1).
    if cust["terms"] == "NET30":
        inv = exposure.create_invoice(cust, "ORDER", order["total_cents"],
                                      order_id=order["id"])
        order["payment_status"] = "INVOICED"
        order["invoice_id"] = inv["id"]
    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    if cust["terms"] == "NET30":
        # Hops 2-3: exposure recompute, possible auto CREDIT_HOLD.
        exposure.on_invoice_created(cust)
    return ok(order)


@bp.route("/orders/<oid>/cancel", methods=["POST"])
@require_roles(*_ROLES)
def cancel_order(oid):
    order = get_order(oid)
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED", "STAGED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order in state %s cannot be cancelled"
                       % order["fulfillment_status"])
    if order["fulfillment_status"] in ("CONFIRMED", "STAGED"):
        # Restore reserved hardgood stock and release route units.
        for line in _hardgood_lines(order):
            product = store.products[line["product_id"]]
            product["stock_on_hand"] += line["qty"]
            touch(product)
        if order["fulfillment"] == "ROUTE":
            route = store.delivery_routes[order["route_id"]]
            route["reserved_units"] -= order["units"]
            touch(route)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(order)
