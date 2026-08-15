"""Sales orders, order lines, stock reservations."""

from datetime import timedelta
from flask import Blueprint, request

import domain
from db import store
from errors import err
from helpers import (get_body, local_time, new_id, now, opt_enum, req_enum,
                     req_int, req_str, stamp_new, touch)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list
from domain import RESERVATION_TTL_HOURS

bp = Blueprint("orders", __name__)


def get_order(oid):
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_ORDER_NOT_FOUND", f"order {oid} not found")
    return o


def get_line(lid):
    l = store.order_lines.get(lid)
    if l is None:
        raise err("ERR_ORDER_LINE_NOT_FOUND", f"order line {lid} not found")
    return l


def get_reservation(rid):
    r = store.reservations.get(rid)
    if r is None:
        raise err("ERR_RESERVATION_NOT_FOUND", f"reservation {rid} not found")
    return r


def _price_order(order, at):
    """Run the full pricing pass over all lines and persist it.
    ORDER_DATE anchors at order.created_at; SHIP_DATE anchors at `at` (now)."""
    branch = store.branches[order["branch_id"]]
    for line in domain.order_lines(order["id"]):
        if line["sourcing_status"] == "CANCELLED":
            continue
        anchor = order["created_at"] if order["price_variant"] == "ORDER_DATE" else at
        vals = domain.compute_line_pricing(order, line, anchor, branch)
        for k, v in vals.items():
            if not k.startswith("_"):
                line[k] = v
        touch(line)
    domain.recompute_order_totals(order)
    order["priced_at"] = at


# ----------------------------------------------------------------- orders --

@bp.route("/motion/orders", methods=["POST"])
@require_roles("CounterSalesRep")
def create_order(user_id, role):
    body = get_body()
    customer_id = req_str(body, "customer_id")
    branch_id = req_str(body, "branch_id")
    if customer_id not in store.customers:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"customer {customer_id} not found")
    if branch_id not in store.branches:
        raise err("ERR_BRANCH_NOT_FOUND", f"branch {branch_id} not found")
    variant = opt_enum(body, "price_variant", ("ORDER_DATE", "SHIP_DATE"), "ORDER_DATE")
    rec = stamp_new({
        "id": new_id(),
        "customer_id": customer_id,
        "branch_id": branch_id,
        "price_variant": variant,
        "fulfillment_status": "DRAFT",
        "billing_status": "UNBILLED",
        "subtotal_cents": 0,
        "expedite_fees_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "priced_at": None,
    })
    store.orders[rec["id"]] = rec
    return ok(serialize("SalesOrder", rec), 201)


@bp.route("/motion/orders", methods=["GET"])
@require_any
def list_orders(user_id, role):
    items = list(store.orders.values())
    q = request.args
    for param, field in (("customer_id", "customer_id"), ("branch_id", "branch_id"),
                         ("fulfillment_status", "fulfillment_status"),
                         ("billing_status", "billing_status")):
        if q.get(param) is not None:
            items = [o for o in items if o[field] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("SalesOrder", page), limit, offset, total)


@bp.route("/motion/orders/<oid>", methods=["GET"])
@require_any
def get_order_route(user_id, role, oid):
    return ok(serialize("SalesOrder", get_order(oid)))


@bp.route("/motion/orders/<oid>/lines", methods=["POST"])
@require_roles("CounterSalesRep")
def add_line(user_id, role, oid):
    order = get_order(oid)
    body = get_body()
    # body FK existence (priority 3); a malformed-typed value defers to shape (7)
    raw_pid = body.get("product_id")
    product_id = raw_pid if isinstance(raw_pid, str) else None
    if product_id is not None and product_id not in store.products:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {product_id} not found")
    # state (priority 5)
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_CONFIRMABLE", "lines may be added only while DRAFT")
    # shape (priority 7)
    if product_id is None:
        raise err("ERR_INVALID_REQUEST", "missing or invalid field: product_id")
    qty = req_int(body, "qty", minimum=1)
    tier = opt_enum(body, "expedite_tier", ("NONE", "STANDARD", "RUSH", "EMERGENCY"), "NONE")
    # referential (priority 9): product must be ACTIVE
    if store.products[product_id]["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_NOT_ACTIVE", "order line requires an ACTIVE product")
    rec = stamp_new({
        "id": new_id(),
        "order_id": oid,
        "product_id": product_id,
        "qty": qty,
        "expedite_tier": tier,
        "unit_price_cents": None,
        "price_protection_applied": False,
        "expedite_fee_cents": 0,
        "line_total_cents": 0,
        "factory_ordered_at": None,
        "shipped_at": None,
        "sourcing_status": "PENDING_SOURCING",
    })
    store.order_lines[rec["id"]] = rec
    touch(order)
    return ok(serialize("OrderLine", rec), 201)


@bp.route("/motion/orders/<oid>/confirm", methods=["POST"])
@require_roles("CounterSalesRep")
def confirm_order(user_id, role, oid):
    order = get_order(oid)
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_CONFIRMABLE", "confirm requires order DRAFT")
    if not domain.order_lines(oid):
        raise err("ERR_ORDER_HAS_NO_LINES", "confirm requires at least one line")
    # price (pure pass first so a credit failure leaves no partial state)
    at = now()
    branch = store.branches[order["branch_id"]]
    plan = []
    for line in domain.order_lines(oid):
        if line["sourcing_status"] == "CANCELLED":
            continue
        anchor = order["created_at"] if order["price_variant"] == "ORDER_DATE" else at
        plan.append((line, domain.compute_line_pricing(order, line, anchor, branch)))
    total = sum(v["_goods"] + v["expedite_fee_cents"] for _, v in plan)
    # fiscal (priority 10): credit hold, then credit limit
    customer = store.customers[order["customer_id"]]
    if customer["credit_status"] != "GOOD":
        raise err("ERR_CUSTOMER_CREDIT_HOLD", "customer is on credit hold")
    if domain.open_receivables(customer["id"]) + total > customer["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED",
                  "open receivables plus order total exceeds credit limit")
    for line, vals in plan:
        for k, v in vals.items():
            if not k.startswith("_"):
                line[k] = v
        touch(line)
    domain.recompute_order_totals(order)
    order["priced_at"] = at
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return ok(serialize("SalesOrder", order))


@bp.route("/motion/orders/<oid>/reprice", methods=["POST"])
@require_roles("CounterSalesRep")
def reprice_order(user_id, role, oid):
    order = get_order(oid)
    # state (priority 5)
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_ORDER_NOT_CONFIRMABLE", "reprice requires DRAFT or CONFIRMED")
    body = get_body()
    expected = req_int(body, "expected_order_version")
    if expected != order["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_order_version does not match the order's current version")
    _price_order(order, now())
    touch(order)
    return ok(serialize("SalesOrder", order))


@bp.route("/motion/orders/<oid>/cancel", methods=["POST"])
@require_roles("CounterSalesRep")
def cancel_order(user_id, role, oid):
    order = get_order(oid)
    lines = domain.order_lines(oid)
    if (order["fulfillment_status"] not in ("DRAFT", "CONFIRMED", "FULLY_SOURCED")
            or any(l["sourcing_status"] == "SHIPPED" for l in lines)):
        raise err("ERR_ORDER_NOT_CANCELLABLE",
                  "cancel requires DRAFT/CONFIRMED/FULLY_SOURCED with no shipped line")
    if order["billing_status"] != "UNBILLED":
        raise err("ERR_ORDER_ALREADY_INVOICED", "cancel requires billing UNBILLED")
    for line in lines:
        if line["sourcing_status"] in ("SHIPPED", "CANCELLED"):
            continue
        line["sourcing_status"] = "CANCELLED"
        touch(line)
        for r in store.reservations.values():
            if r["order_line_id"] == line["id"] and r["status"] == "ACTIVE":
                r["status"] = "RELEASED"
                touch(r)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(serialize("SalesOrder", order))


@bp.route("/motion/orders/<oid>/invoice", methods=["POST"])
@require_roles("BranchManager")
def invoice_order(user_id, role, oid):
    order = get_order(oid)
    if order["fulfillment_status"] != "SHIPPED":
        raise err("ERR_ORDER_NOT_FULLY_SHIPPED", "invoice requires fulfillment SHIPPED")
    if order["billing_status"] != "UNBILLED":
        raise err("ERR_ORDER_ALREADY_INVOICED", "invoice requires billing UNBILLED")
    order["billing_status"] = "INVOICED"
    touch(order)
    return ok(serialize("SalesOrder", order))


@bp.route("/motion/orders/<oid>/record-payment", methods=["POST"])
@require_roles("BranchManager")
def record_payment(user_id, role, oid):
    order = get_order(oid)
    if order["billing_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise err("ERR_ORDER_ALREADY_INVOICED",
                  "record-payment requires an invoiced order")
    body = get_body()
    amount = req_int(body, "amount_cents")
    remaining = order["total_cents"] - order["paid_cents"]
    if amount <= 0 or amount > remaining:
        raise err("ERR_INVALID_REQUEST",
                  "amount_cents must be > 0 and <= total_cents - paid_cents")
    order["paid_cents"] += amount
    order["billing_status"] = "PAID" if order["paid_cents"] == order["total_cents"] else "PARTIALLY_PAID"
    touch(order)
    return ok(serialize("SalesOrder", order))


@bp.route("/motion/orders/<oid>/close", methods=["POST"])
@require_roles("BranchManager")
def close_order(user_id, role, oid):
    order = get_order(oid)
    if order["fulfillment_status"] != "SHIPPED":
        raise err("ERR_ORDER_NOT_FULLY_SHIPPED", "close requires fulfillment SHIPPED")
    if order["billing_status"] != "PAID":
        raise err("ERR_ORDER_NOT_PAID", "close requires billing PAID")
    order["fulfillment_status"] = "CLOSED"
    touch(order)
    return ok(serialize("SalesOrder", order))


# ------------------------------------------------------------ order lines --

@bp.route("/motion/order-lines", methods=["GET"])
@require_any
def list_lines(user_id, role):
    items = list(store.order_lines.values())
    q = request.args
    for param, field in (("order_id", "order_id"), ("product_id", "product_id"),
                         ("sourcing_status", "sourcing_status")):
        if q.get(param) is not None:
            items = [l for l in items if l[field] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("OrderLine", page), limit, offset, total)


@bp.route("/motion/order-lines/<lid>", methods=["GET"])
@require_any
def get_line_route(user_id, role, lid):
    return ok(serialize("OrderLine", get_line(lid)))


@bp.route("/motion/order-lines/<lid>/expedite", methods=["POST"])
@require_roles("CounterSalesRep")
def change_expedite(user_id, role, lid):
    line = get_line(lid)
    order = store.orders[line["order_id"]]
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_CONFIRMABLE", "expedite change requires order DRAFT")
    body = get_body()
    tier = req_enum(body, "expedite_tier", ("NONE", "STANDARD", "RUSH", "EMERGENCY"))
    line["expedite_tier"] = tier
    touch(line)
    touch(order)
    return ok(serialize("OrderLine", line))


@bp.route("/motion/order-lines/<lid>/reserve", methods=["POST"])
@require_roles("CounterSalesRep")
def reserve_line(user_id, role, lid):
    line = get_line(lid)
    body = get_body()
    # body FK existence (priority 3); malformed-typed value defers to shape (7)
    raw_sid = body.get("branch_stock_id")
    stock_id = raw_sid if isinstance(raw_sid, str) else None
    stock = store.stocks.get(stock_id) if stock_id else None
    if stock_id is not None and stock is None:
        raise err("ERR_BRANCH_STOCK_NOT_FOUND", f"branch stock {stock_id} not found")
    # state (priority 5): line first, then order
    if line["sourcing_status"] != "PENDING_SOURCING":
        raise err("ERR_LINE_NOT_SOURCABLE", "reserve requires line PENDING_SOURCING")
    order = store.orders[line["order_id"]]
    if order["fulfillment_status"] not in ("CONFIRMED", "FULLY_SOURCED"):
        raise err("ERR_ORDER_NOT_CONFIRMABLE",
                  "reserve requires order CONFIRMED or FULLY_SOURCED")
    # shape (priority 7)
    if stock_id is None:
        raise err("ERR_INVALID_REQUEST", "missing or invalid field: branch_stock_id")
    qty = req_int(body, "qty", minimum=1)
    # referential (priority 9): branch/product match, then full-line qty
    if stock["branch_id"] != order["branch_id"] or stock["product_id"] != line["product_id"]:
        raise err("ERR_STOCK_LINE_MISMATCH",
                  "stock record must match the order's branch and the line's product")
    if qty != line["qty"]:
        raise err("ERR_PARTIAL_RESERVATION", "reservation qty must equal the line qty")
    # fiscal (priority 10)
    if domain.available_qty(stock) < qty:
        raise err("ERR_INSUFFICIENT_AVAILABLE_STOCK", "available_qty < requested qty")
    rec = stamp_new({
        "id": new_id(),
        "order_line_id": lid,
        "branch_stock_id": stock_id,
        "qty": qty,
        "expires_at": now() + timedelta(hours=RESERVATION_TTL_HOURS),
        "status": "ACTIVE",
    })
    store.reservations[rec["id"]] = rec
    line["sourcing_status"] = "STOCK_RESERVED"
    touch(line)
    domain.reevaluate_order_fulfillment(order)
    return ok(serialize("StockReservation", rec), 201)


@bp.route("/motion/order-lines/<lid>/place-factory-order", methods=["POST"])
@require_roles("CounterSalesRep")
def place_factory_order(user_id, role, lid):
    line = get_line(lid)
    if line["sourcing_status"] != "PENDING_SOURCING":
        raise err("ERR_LINE_NOT_SOURCABLE", "factory order requires line PENDING_SOURCING")
    order = store.orders[line["order_id"]]
    if order["fulfillment_status"] not in ("CONFIRMED", "FULLY_SOURCED"):
        raise err("ERR_ORDER_NOT_CONFIRMABLE",
                  "factory order requires order CONFIRMED or FULLY_SOURCED")
    branch = store.branches[order["branch_id"]]
    if line["expedite_tier"] in ("NONE", "STANDARD"):
        if local_time(branch).hour >= branch["expedite_cutoff_hour"]:
            raise err("ERR_FACTORY_ORDER_CUTOFF_PASSED",
                      "NONE/STANDARD tier at/after branch expedite cutoff")
    line["sourcing_status"] = "FACTORY_ORDERED"
    line["factory_ordered_at"] = now()
    touch(line)
    domain.reevaluate_order_fulfillment(order)
    return ok(serialize("OrderLine", line))


@bp.route("/motion/order-lines/<lid>/receive-factory", methods=["POST"])
@require_roles("BranchManager")
def receive_factory(user_id, role, lid):
    line = get_line(lid)
    if line["sourcing_status"] != "FACTORY_ORDERED":
        raise err("ERR_LINE_NOT_FACTORY_ORDERED", "receive requires line FACTORY_ORDERED")
    order = store.orders[line["order_id"]]
    stock = domain.find_stock(order["branch_id"], line["product_id"])
    lead = stock["factory_lead_time_days"] if stock else 0
    if line["expedite_tier"] == "EMERGENCY":
        effective_days = 0
    elif line["expedite_tier"] == "RUSH":
        effective_days = max(lead // 2, 1)
    else:
        effective_days = lead
    if now() < line["factory_ordered_at"] + timedelta(days=effective_days):
        raise err("ERR_FACTORY_LEAD_TIME_UNMET",
                  "factory receipt before tier-adjusted lead time elapsed")
    if stock is not None:
        stock["on_hand_qty"] += line["qty"]
        touch(stock)
    line["sourcing_status"] = "FACTORY_RECEIVED"
    touch(line)
    domain.reevaluate_order_fulfillment(order)
    return ok(serialize("OrderLine", line))


@bp.route("/motion/order-lines/<lid>/allocate", methods=["POST"])
@require_roles("BranchManager")
def allocate_line(user_id, role, lid):
    line = get_line(lid)
    if line["sourcing_status"] not in ("STOCK_RESERVED", "FACTORY_RECEIVED"):
        raise err("ERR_LINE_NOT_ALLOCATABLE",
                  "allocate requires STOCK_RESERVED or FACTORY_RECEIVED")
    order = store.orders[line["order_id"]]
    stock = domain.find_stock(order["branch_id"], line["product_id"])
    if line["sourcing_status"] == "STOCK_RESERVED":
        for r in store.reservations.values():
            if r["order_line_id"] == lid and r["status"] == "ACTIVE":
                r["status"] = "CONSUMED"
                touch(r)
    if stock is not None:
        stock["on_hand_qty"] -= line["qty"]
        touch(stock)
    line["sourcing_status"] = "ALLOCATED"
    touch(line)
    domain.reevaluate_order_fulfillment(order)
    return ok(serialize("OrderLine", line))


@bp.route("/motion/order-lines/<lid>/ship", methods=["POST"])
@require_roles("BranchManager")
def ship_line(user_id, role, lid):
    line = get_line(lid)
    if line["sourcing_status"] != "ALLOCATED":
        raise err("ERR_LINE_NOT_SHIPPABLE", "ship requires line ALLOCATED")
    at = now()
    line["shipped_at"] = at
    line["sourcing_status"] = "SHIPPED"
    touch(line)
    order = store.orders[line["order_id"]]
    if order["price_variant"] == "SHIP_DATE":
        # re-price this line anchored at shipped_at; fee recomputes only if
        # the protected amount changed (expedite_fee_stacking trigger note)
        branch = store.branches[order["branch_id"]]
        vals = domain.compute_line_pricing(order, line, at, branch)
        if vals["unit_price_cents"] != line["unit_price_cents"]:
            line["expedite_fee_cents"] = vals["expedite_fee_cents"]
        line["unit_price_cents"] = vals["unit_price_cents"]
        line["price_protection_applied"] = vals["price_protection_applied"]
    domain.recompute_order_totals(order)
    domain.reevaluate_order_fulfillment(order)
    return ok(serialize("OrderLine", line))


# ----------------------------------------------------------- reservations --

@bp.route("/motion/stock-reservations", methods=["GET"])
@require_any
def list_reservations(user_id, role):
    items = list(store.reservations.values())
    q = request.args
    for param in ("order_line_id", "branch_stock_id", "status"):
        if q.get(param) is not None:
            items = [r for r in items if r[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("StockReservation", page), limit, offset, total)


@bp.route("/motion/stock-reservations/<rid>", methods=["GET"])
@require_any
def get_reservation_route(user_id, role, rid):
    return ok(serialize("StockReservation", get_reservation(rid)))


@bp.route("/motion/stock-reservations/<rid>/release", methods=["POST"])
@require_roles("CounterSalesRep", "BranchManager")
def release_reservation(user_id, role, rid):
    res = get_reservation(rid)
    if res["status"] != "ACTIVE":
        raise err("ERR_RESERVATION_NOT_ACTIVE", "release requires reservation ACTIVE")
    res["status"] = "RELEASED"
    touch(res)
    line = store.order_lines.get(res["order_line_id"])
    if line and line["sourcing_status"] == "STOCK_RESERVED":
        line["sourcing_status"] = "PENDING_SOURCING"
        touch(line)
        order = store.orders.get(line["order_id"])
        if order:
            domain.reevaluate_order_fulfillment(order)
    return ok(serialize("StockReservation", res))
