"""Institutional buyers, orders, demand lines, aggregation and settlement."""

from flask import Blueprint, request

import cascade
import domain
import fetch
import pricing
import serializers
from constants import (BUYER_TYPES, PAYMENT_TERMS_DAYS, ROLE_BUYER,
                       ROLE_HUB_ADMIN, ROLE_PRODUCER, STORAGE_CLASSES,
                       UNITS_OF_MEASURE)
from envelope import list_response, ok
from errors import ApiError
from store import add_days, base_record, db, now, sorted_records, touch
from validators import (actor, body, endpoint, req_datetime, req_enum, req_int,
                        req_string)

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# buyers
# ---------------------------------------------------------------------------

@bp.post("/buyers")
@endpoint([ROLE_HUB_ADMIN])
def create_buyer():
    payload = body()
    legal_name = req_string(payload, "legal_name", min_len=1, max_len=120)
    buyer_type = req_enum(payload, "buyer_type", BUYER_TYPES)
    dock_zone_code = req_string(payload, "dock_zone_code", min_len=1, max_len=12)
    terms = req_int(payload, "payment_terms_days")
    if terms not in PAYMENT_TERMS_DAYS:
        raise ApiError("ERR_INVALID_REQUEST", "payment_terms_days must be 15, 30 or 45.")
    credit_limit = req_int(payload, "credit_limit_cents", minimum=0)

    buyer = base_record({
        "legal_name": legal_name,
        "buyer_type": buyer_type,
        "dock_zone_code": dock_zone_code,
        "payment_terms_days": terms,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
    })
    db.buyers[buyer["id"]] = buyer
    return ok(serializers.buyer_out(buyer), 201)


@bp.get("/buyers/<buyer_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_BUYER])
def read_buyer(buyer_id):
    buyer = fetch.get("buyer", buyer_id)
    return ok(serializers.buyer_out(buyer))


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------

@bp.post("/buyer-orders")
@endpoint([ROLE_BUYER, ROLE_HUB_ADMIN])
def create_order():
    payload = body()
    buyer = fetch.body_fk(payload, "buyer_id", "buyer")          # rung 5
    req_string(payload, "buyer_id")                              # rung 6
    requested = req_datetime(payload, "requested_delivery_date")

    user_id, role = actor()
    if role == ROLE_BUYER and user_id != buyer["id"]:            # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    order = base_record({
        "buyer_id": buyer["id"],
        "requested_delivery_date": requested,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNBILLED",
        "producer_subtotal_cents": 0,
        "hub_margin_cents": 0,
        "order_total_cents": 0,
        "margin_tier_bp": 0,
        "invoiced_total_cents": 0,
        "paid_total_cents": 0,
        "credit_memo_cents": 0,
        "invoice_due_date": None,
        "route_id": None,
        "route_sequence_no": None,
        "planned_arrival_at": None,
        "service_minutes": None,
        "order_pallets": 0,
    })
    db.orders[order["id"]] = order
    return ok(serializers.order_out(order), 201)


@bp.get("/buyer-orders/<order_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_BUYER])
def read_order(order_id):
    order = fetch.get("order", order_id)
    return ok(serializers.order_out(order))


@bp.get("/buyer-orders")
@endpoint([ROLE_HUB_ADMIN, ROLE_BUYER])
def list_orders():
    records = sorted_records(list(db.orders.values()))
    for field in ("buyer_id", "route_id", "fulfillment_status", "settlement_status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    return list_response(records, serializers.order_out)


# ---------------------------------------------------------------------------
# demand lines
# ---------------------------------------------------------------------------

@bp.post("/buyer-orders/<order_id>/lines")
@endpoint([ROLE_BUYER, ROLE_HUB_ADMIN])
def add_line(order_id):
    order = fetch.get("order", order_id)                         # rung 4
    payload = body()
    commodity_code = req_string(payload, "commodity_code", min_len=1, max_len=40)
    storage_class = req_enum(payload, "storage_class", STORAGE_CLASSES)
    unit_of_measure = req_enum(payload, "unit_of_measure", UNITS_OF_MEASURE)
    quantity_requested = req_int(payload, "quantity_requested", minimum=1)
    max_unit_price = req_int(payload, "max_unit_price_cents", minimum=1)

    user_id, role = actor()
    if role == ROLE_BUYER and user_id != order["buyer_id"]:      # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if order["fulfillment_status"] != "DRAFT":                   # rung 10
        raise ApiError("ERR_INVALID_ORDER_STATE")

    line = base_record({
        "order_id": order["id"],
        "commodity_code": commodity_code,
        "storage_class": storage_class,
        "unit_of_measure": unit_of_measure,
        "quantity_requested": quantity_requested,
        "max_unit_price_cents": max_unit_price,
        "quantity_allocated": 0,
        "quantity_delivered": 0,
        "quantity_rejected": 0,
        "line_producer_cents": 0,
        "line_margin_cents": 0,
        "line_total_cents": 0,
        "status": "PENDING",
    })
    db.lines[line["id"]] = line
    return ok(serializers.line_out(line), 201)


@bp.get("/buyer-orders/<order_id>/lines")
@endpoint([ROLE_HUB_ADMIN, ROLE_BUYER])
def list_lines(order_id):
    fetch.get("order", order_id)
    records = domain.order_lines(order_id)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, serializers.line_out)


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

@bp.post("/buyer-orders/<order_id>/aggregation")
@endpoint([ROLE_HUB_ADMIN])
def run_aggregation(order_id):
    order = fetch.get("order", order_id)                         # rung 4
    # rung 10
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    lines = domain.order_lines(order["id"])
    if not lines:
        raise ApiError("ERR_INVALID_ORDER_STATE", "The order carries no demand lines.")

    plan, per_line = pricing.plan_allocations(order)

    # rung 25 — the empty-pool fallback is per line; only a whole-order miss fails
    if sum(per_line.values()) == 0:
        raise ApiError("ERR_NO_ELIGIBLE_SUPPLY")

    provisional = pricing.compute_money(
        [(item["quantity"], item["producer_unit_price_cents"]) for item in plan])

    # rung 30 — buyer credit exposure; nothing is persisted when it fails
    buyer = db.buyers.get(order["buyer_id"])
    if buyer is not None:
        exposure = buyer["outstanding_balance_cents"] + provisional["order_total"]
        if exposure > buyer["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    pricing.commit_allocations(order, plan, per_line)
    order["fulfillment_status"] = "AGGREGATED"
    touch(order)
    return ok(serializers.order_out(order))


# ---------------------------------------------------------------------------
# delivery record
# ---------------------------------------------------------------------------

@bp.post("/buyer-orders/<order_id>/delivery-record")
@endpoint([ROLE_HUB_ADMIN])
def record_delivery(order_id):
    order = fetch.get("order", order_id)                         # rung 4
    payload = body()
    receipts = payload.get("line_receipts")

    # rung 5 — every referenced allocation must resolve
    if isinstance(receipts, list):
        for entry in receipts:
            if isinstance(entry, dict) and isinstance(entry.get("allocation_id"), str):
                fetch.get("allocation", entry["allocation_id"])

    # rung 6 — request shape
    if not isinstance(receipts, list) or not receipts:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'line_receipts' must be a non-empty array.")
    parsed = []
    for entry in receipts:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each line_receipts entry must be an object.")
        allocation_id = entry.get("allocation_id")
        if not isinstance(allocation_id, str) or allocation_id.strip() == "":
            raise ApiError("ERR_INVALID_REQUEST", "Each line_receipts entry needs an allocation_id.")
        allocation = db.allocations.get(allocation_id)
        if allocation is None:
            raise ApiError("ERR_ALLOCATION_NOT_FOUND")
        quantity = entry.get("delivered_quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ApiError("ERR_INVALID_REQUEST", "delivered_quantity must be an integer.")
        if quantity < 0 or quantity > allocation["quantity"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "delivered_quantity must be between 0 and the reserved quantity.")
        parsed.append((allocation, quantity))

    # rung 10
    if order["fulfillment_status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_ORDER_STATE")

    # rung 16 — each receipted allocation belongs to a line of this order
    order_line_ids = set(l["id"] for l in domain.order_lines(order["id"]))
    for allocation, _quantity in parsed:
        if allocation["order_line_id"] not in order_line_ids:
            raise ApiError("ERR_ALLOCATION_NOT_FOUND")

    for allocation, quantity in parsed:
        allocation["delivered_quantity"] = quantity
        if quantity > 0:
            allocation["status"] = "DELIVERED"
        else:
            allocation["status"] = "SHORT_CLOSED"
            product = db.products.get(allocation["product_id"])
            if product is not None:
                product["quantity_committed"] = max(
                    0, product["quantity_committed"] - allocation["quantity"])
                domain.recompute_product_available(product)
                touch(product)
            allocation["producer_amount_cents"] = 0
            allocation["hub_margin_cents"] = 0
            allocation["buyer_amount_cents"] = 0
        touch(allocation)

    for line in domain.order_lines(order["id"]):
        delivered = domain.line_quantity_delivered(line)
        changed = line["quantity_delivered"] != delivered
        line["quantity_delivered"] = delivered
        if delivered > 0 and line["status"] in ("ALLOCATED", "SHORT"):
            line["status"] = "DELIVERED"
            changed = True
        if changed:
            touch(line)

    order["fulfillment_status"] = "DELIVERED"
    touch(order)

    route = db.routes.get(order.get("route_id")) if order.get("route_id") else None
    cascade.advance_completed_route(route)

    return ok(serializers.order_out(order))


# ---------------------------------------------------------------------------
# settlement
# ---------------------------------------------------------------------------

@bp.post("/buyer-orders/<order_id>/invoice")
@endpoint([ROLE_HUB_ADMIN])
def invoice_order(order_id):
    order = fetch.get("order", order_id)                         # rung 4
    # rung 10
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["settlement_status"] != "UNBILLED":
        raise ApiError("ERR_INVALID_ORDER_STATE")

    pricing.run_rollup(order, "final")
    order["invoiced_total_cents"] = order["order_total_cents"]

    buyer = db.buyers.get(order["buyer_id"])
    terms = buyer["payment_terms_days"] if buyer is not None else 0
    order["invoice_due_date"] = add_days(now(), terms)
    if buyer is not None:
        buyer["outstanding_balance_cents"] += order["invoiced_total_cents"]
        touch(buyer)

    order["settlement_status"] = "INVOICED"
    touch(order)
    return ok(serializers.order_out(order))


@bp.post("/buyer-orders/<order_id>/payments")
@endpoint([ROLE_BUYER, ROLE_HUB_ADMIN])
def apply_payment(order_id):
    order = fetch.get("order", order_id)                         # rung 4
    payload = body()
    amount = req_int(payload, "amount_cents", minimum=1)         # rung 6

    user_id, role = actor()
    if role == ROLE_BUYER and user_id != order["buyer_id"]:      # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 11 — payment admissibility
    if order["settlement_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise ApiError("ERR_ORDER_NOT_INVOICED")

    # rung 29 — headroom against the invoiced balance
    balance = (order["invoiced_total_cents"] - order["paid_total_cents"]
               - order["credit_memo_cents"])
    if amount > balance:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    order["paid_total_cents"] += amount
    buyer = db.buyers.get(order["buyer_id"])
    if buyer is not None:
        buyer["outstanding_balance_cents"] -= amount
        touch(buyer)

    if order["paid_total_cents"] + order["credit_memo_cents"] >= order["invoiced_total_cents"]:
        order["settlement_status"] = "PAID"
        cascade.credit_patronage(order)
        cascade.close_fulfillment(order)
    else:
        order["settlement_status"] = "PARTIALLY_PAID"

    touch(order)
    return ok(serializers.order_out(order))


# ---------------------------------------------------------------------------
# allocations
# ---------------------------------------------------------------------------

@bp.get("/allocations/<allocation_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER, ROLE_BUYER])
def read_allocation(allocation_id):
    allocation = fetch.get("allocation", allocation_id)
    return ok(serializers.allocation_out(allocation))


@bp.get("/allocations")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER, ROLE_BUYER])
def list_allocations():
    records = sorted_records(list(db.allocations.values()))
    for field in ("order_line_id", "product_id", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return list_response(records, serializers.allocation_out)
