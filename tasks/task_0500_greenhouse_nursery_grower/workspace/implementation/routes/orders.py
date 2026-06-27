from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  req_str, req_int, req_datetime, ApiError,
                  ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_STALE_VERSION,
                  ERR_EMPTY_ORDER, ERR_BROKER_ON_HOLD, ERR_INSUFFICIENT_AVAILABILITY,
                  ERR_CREDIT_LIMIT_EXCEEDED, ERR_ORDER_HAS_SHIPMENT)
import services as svc

bp = Blueprint("orders", __name__)

ROLES = ["SalesCoordinator", "Broker"]


def _enforce_owns(order, uid, role):
    if role == "Broker" and order["broker_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, "Broker may only act on its own orders")


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@bp.post("/nursery/orders")
def create_order():
    uid, role = require(ROLES)
    body = get_body()
    raw_bid = body.get("broker_id")
    if isinstance(raw_bid, str) and raw_bid not in store.brokers:
        raise ApiError(ERR_NOT_FOUND, "Broker not found")
    broker_id = req_str(body, "broker_id")
    requested_ship_date = req_datetime(body, "requested_ship_date")
    if broker_id not in store.brokers:
        raise ApiError(ERR_NOT_FOUND, "Broker not found")
    if role == "Broker" and broker_id != uid:
        raise ApiError(ERR_FORBIDDEN, "Broker may only create its own orders")
    o = common_create({
        "broker_id": broker_id,
        "requested_ship_date": requested_ship_date,
        "order_subtotal_cents": 0,
        "freight_cents": 0,
        "order_total_cents": 0,
        "status": "DRAFT",
    })
    store.orders[o["id"]] = o
    return ok(o, 201)


@bp.get("/nursery/orders/<oid>")
def get_order(oid):
    uid, role = require(ROLES)
    o = get_or_404(store.orders, oid)
    _enforce_owns(o, uid, role)
    return ok(o)


@bp.get("/nursery/orders")
def list_orders():
    uid, role = require(ROLES)
    rows = list(store.orders.values())
    if role == "Broker":
        rows = [r for r in rows if r["broker_id"] == uid]
    status = request.args.get("status")
    broker_id = request.args.get("broker_id")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@bp.post("/nursery/orders/<oid>/lines")
def add_line(oid):
    uid, role = require(ROLES)
    o = get_or_404(store.orders, oid)
    body = get_body()
    raw_eid = body.get("availability_entry_id")
    if isinstance(raw_eid, str) and raw_eid not in store.availability:
        raise ApiError(ERR_NOT_FOUND, "Availability entry not found")
    availability_entry_id = req_str(body, "availability_entry_id")
    quantity = req_int(body, "quantity", minimum=1)
    if availability_entry_id not in store.availability:
        raise ApiError(ERR_NOT_FOUND, "Availability entry not found")
    _enforce_owns(o, uid, role)
    if o["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Lines can only be added to a DRAFT order")
    entry = store.availability[availability_entry_id]
    unit_price_cents = entry["unit_price_cents"]
    line = common_create({
        "order_id": oid,
        "availability_entry_id": availability_entry_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "extended_cents": quantity * unit_price_cents,
        "shipped_quantity": 0,
        "status": "PENDING",
    })
    store.order_lines[line["id"]] = line
    svc.recompute_order(o)
    touch(o)
    return ok(line, 201)


@bp.get("/nursery/orders/<oid>/lines")
def list_order_lines(oid):
    uid, role = require(ROLES)
    o = get_or_404(store.orders, oid)
    _enforce_owns(o, uid, role)
    rows = [l for l in store.order_lines.values() if l["order_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/nursery/order-lines/<lid>")
def get_line(lid):
    uid, role = require(ROLES)
    line = get_or_404(store.order_lines, lid)
    o = store.orders.get(line["order_id"])
    if o is not None:
        _enforce_owns(o, uid, role)
    return ok(line)


@bp.get("/nursery/order-lines")
def list_lines():
    uid, role = require(ROLES)
    rows = list(store.order_lines.values())
    if role == "Broker":
        owned = {o["id"] for o in store.orders.values() if o["broker_id"] == uid}
        rows = [l for l in rows if l["order_id"] in owned]
    for key in ("order_id", "availability_entry_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.delete("/nursery/order-lines/<lid>")
def remove_line(lid):
    uid, role = require(ROLES)
    line = get_or_404(store.order_lines, lid)
    o = store.orders.get(line["order_id"])
    if o is not None:
        _enforce_owns(o, uid, role)
    if o is None or o["status"] != "DRAFT" or line["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING line on a DRAFT order can be removed")
    line["status"] = "RELEASED"
    touch(line)
    svc.recompute_order(o)
    touch(o)
    return ok(line)


# ---------------------------------------------------------------------------
# Confirm / cancel
# ---------------------------------------------------------------------------
@bp.post("/nursery/orders/<oid>/confirm")
def confirm_order(oid):
    require(["SalesCoordinator"])
    o = get_or_404(store.orders, oid)
    body = get_body()
    expected_order_version = req_int(body, "expected_order_version")
    if o["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT order can be confirmed")
    lines = [l for l in store.order_lines.values() if l["order_id"] == oid and l["status"] == "PENDING"]
    if not lines:
        raise ApiError(ERR_EMPTY_ORDER, "Order has no lines")
    broker = store.brokers.get(o["broker_id"])
    if broker["status"] != "ACTIVE":
        raise ApiError(ERR_BROKER_ON_HOLD, "Broker is ON_HOLD")
    svc.recompute_order(o)
    for l in lines:
        entry = store.availability.get(l["availability_entry_id"])
        if entry is None or l["quantity"] > entry["available_quantity"]:
            raise ApiError(ERR_INSUFFICIENT_AVAILABILITY, "Line quantity exceeds available inventory")
    if broker["open_balance_cents"] + o["order_total_cents"] > broker["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, "Order exceeds broker credit limit")
    if expected_order_version != o["version"]:
        raise ApiError(ERR_STALE_VERSION, "Order version is stale")
    # commit
    for l in lines:
        entry = store.availability[l["availability_entry_id"]]
        l["status"] = "COMMITTED"
        touch(l)
        entry["committed_quantity"] += l["quantity"]
        svc.recompute_availability(entry)
        touch(entry)
    broker["open_balance_cents"] += o["order_total_cents"]
    touch(broker)
    o["status"] = "CONFIRMED"
    touch(o)
    return ok(o)


@bp.post("/nursery/orders/<oid>/cancel")
def cancel_order(oid):
    require(["SalesCoordinator"])
    o = get_or_404(store.orders, oid)
    if o["status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT or CONFIRMED order can be cancelled")
    if o["status"] == "DRAFT":
        for l in store.order_lines.values():
            if l["order_id"] == oid and l["status"] == "PENDING":
                l["status"] = "RELEASED"
                touch(l)
        o["status"] = "CANCELLED"
        touch(o)
        return ok(o)
    # CONFIRMED cancel = compensation
    for sh in store.shipments.values():
        if sh["order_id"] == oid and sh["status"] == "DISPATCHED":
            raise ApiError(ERR_ORDER_HAS_SHIPMENT, "Order has a dispatched shipment")
    broker = store.brokers.get(o["broker_id"])
    for l in store.order_lines.values():
        if l["order_id"] == oid and l["status"] == "COMMITTED":
            l["status"] = "RELEASED"
            touch(l)
            entry = store.availability.get(l["availability_entry_id"])
            if entry is not None:
                entry["committed_quantity"] -= l["quantity"]
                svc.recompute_availability(entry)
                touch(entry)
    if broker is not None:
        broker["open_balance_cents"] -= o["order_total_cents"]
        touch(broker)
    o["status"] = "CANCELLED"
    touch(o)
    return ok(o)
