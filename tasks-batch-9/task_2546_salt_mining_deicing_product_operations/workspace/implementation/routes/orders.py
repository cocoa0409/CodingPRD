"""Delivery orders: the storm waterfall, the invoice and penalty reconciliation."""

from flask import Blueprint

import db
import response
from db import store, touch
from errors import (
    ERR_CONTRACT_INVALID_STATE,
    ERR_DEPOT_CLOSED,
    ERR_NO_ELIGIBLE_STOCKPILE,
    ERR_ORDER_INVALID_STATE,
    ERR_PENALTY_NOT_ACCRUED,
    ERR_STALE_BID_CONTRACT_VERSION,
    ERR_TAKE_BAND_EXCEEDED,
    fail,
    invalid,
)
from middleware import auth
from services import alloc, calc, derive, serialize
from util import (D, ZERO, body, enum, filter_str, number, parse_iso, present, q2,
                  require, text)

bp = Blueprint("orders", __name__)

STORM_PRIORITIES = ("ROUTINE", "STORM_EMERGENCY")


def _require_status(order, allowed):
    if order["status"] not in allowed:
        fail(ERR_ORDER_INVALID_STATE,
             "order status %s does not admit this operation" % order["status"])


@bp.post("/salt/delivery-orders")
@auth("ContractAdministrator", "LogisticsPlanner")
def create_order():
    payload = body()
    require(payload, ["bid_contract_id", "depot_id", "requested_tons",
                      "required_by", "market_index_price_per_ton",
                      "expected_bid_contract_version"])
    priority = "ROUTINE"
    if present(payload, "storm_priority"):
        priority = enum(payload, "storm_priority", STORM_PRIORITIES)
    requested = number(payload, "requested_tons", gt=0)
    market_price = number(payload, "market_index_price_per_ton", minv=0)
    required_by = parse_iso(payload["required_by"], "required_by")
    if not required_by > db.now():
        invalid("required_by must be strictly after the current logical clock")

    contract = derive.get_contract(payload["bid_contract_id"])
    depot = derive.get_depot(payload["depot_id"])

    if payload["expected_bid_contract_version"] != contract["version"]:
        fail(ERR_STALE_BID_CONTRACT_VERSION,
             "expected_bid_contract_version %s does not match the contract's %s"
             % (payload["expected_bid_contract_version"], contract["version"]))
    if contract["status"] != "ACTIVE":
        fail(ERR_CONTRACT_INVALID_STATE,
             "contract status %s does not admit a delivery order"
             % contract["status"])
    if depot["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the named depot is closed")

    consumed = derive.contract_take_band_consumed(contract["id"])
    limit = D(contract["committed_tons"]) * D(contract["max_take_pct"]) / D(100)
    if D(consumed) + D(requested) > limit:
        fail(ERR_TAKE_BAND_EXCEEDED,
             "consumed %s plus %s exceeds the take-band limit %s"
             % (consumed, requested, limit))

    order = db.stamp()
    order.update({
        "bid_contract_id": contract["id"],
        "depot_id": depot["id"],
        "requested_tons": requested,
        "required_by": required_by,
        "storm_priority": priority,
        "market_index_price_per_ton": market_price,
        "shorted_tons": q2(ZERO),
        "status": "REQUESTED",
        "penalty_state": "NONE",
        "shortfall_penalty_usd": q2(ZERO),
        "product_subtotal_usd": None,
        "freight_subtotal_usd": None,
        "storm_surcharge_usd": None,
        "guarantee_credit_usd": None,
        "invoice_total_usd": None,
        "delivered_at": None,
    })
    store.orders[order["id"]] = order
    touch(contract)
    return response.created(serialize.order_json(order))


@bp.get("/salt/delivery-orders/<order_id>")
@auth()
def read_order(order_id):
    return response.ok(serialize.order_json(derive.get_order(order_id)))


@bp.get("/salt/delivery-orders")
@auth()
def list_orders():
    rows = list(store.orders.values())
    for name in ("bid_contract_id", "depot_id", "status", "penalty_state",
                 "storm_priority"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.order_json)


@bp.post("/salt/delivery-orders/<order_id>/allocate")
@auth("LogisticsPlanner")
def allocate_order(order_id):
    order = derive.get_order(order_id)
    contract = derive.get_contract(order["bid_contract_id"])
    _require_status(order, ("REQUESTED",))

    pool = alloc.candidate_lots(order, contract)
    if not pool:
        fail(ERR_NO_ELIGIBLE_STOCKPILE,
             "no eligible stockpile lot is available for this order")

    outstanding = D(order["requested_tons"])
    rank = 0
    for (lot, _depot) in pool:
        if outstanding <= ZERO:
            break
        available = derive.lot_available_tons(lot)
        if available <= ZERO:
            continue
        taken = available if available < outstanding else outstanding
        rank += 1
        alloc.new_allocation(order, lot, taken, "WATERFALL", rank)
        outstanding = q2(outstanding - D(taken))

    allocated = derive.order_allocated_tons(order["id"])
    if D(allocated) >= D(order["requested_tons"]):
        order["status"] = "ALLOCATED"
        order["shorted_tons"] = q2(ZERO)
        order["penalty_state"] = "NONE"
    else:
        order["status"] = "SHORTED"
        alloc.accrue_shortfall(order, contract, allocated)
    touch(order)
    return response.ok(serialize.order_json(order))


@bp.post("/salt/delivery-orders/<order_id>/release-allocations")
@auth("LogisticsPlanner")
def release_allocations(order_id):
    order = derive.get_order(order_id)
    contract = derive.get_contract(order["bid_contract_id"])
    _require_status(order, ("ALLOCATED", "SHORTED"))

    for row in db.by_seq(derive.allocations_of_order(order["id"])):
        if row["state"] == "RESERVED":
            alloc.release_allocation(row)

    order["status"] = "REQUESTED"
    alloc.clear_shortfall(order, contract)
    touch(order)
    return response.ok(serialize.order_json(order))


def _invoice(order, contract):
    rows = [r for r in derive.allocations_of_order(order["id"])
            if r["state"] in ("RESERVED", "CONSUMED")]
    rows = db.by_seq(rows)
    product = ZERO
    freight = ZERO
    allocated = ZERO
    for row in rows:
        tons = D(row["tons"])
        allocated += tons
        product += q2(tons * D(contract["guaranteed_price_per_ton"]))
        lot = store.lots.get(row["stockpile_lot_id"])
        depot = store.depots.get(lot["depot_id"]) if lot is not None else None
        rate = D(depot["outbound_freight_rate_per_ton"]) if depot else ZERO
        freight += q2(tons * rate)

    product = q2(product)
    freight = q2(freight)
    if order["storm_priority"] == "STORM_EMERGENCY":
        surcharge = q2((product + freight) * D("0.06"))
    else:
        surcharge = q2(ZERO)

    ceiling = (D(contract["guaranteed_price_per_ton"])
               * (D(1) + D(contract["price_guarantee_cap_pct"]) / D(100)))
    excess = D(order["market_index_price_per_ton"]) - ceiling
    if excess < ZERO:
        excess = ZERO
    credit = q2(excess * allocated)

    order["product_subtotal_usd"] = product
    order["freight_subtotal_usd"] = freight
    order["storm_surcharge_usd"] = surcharge
    order["guarantee_credit_usd"] = credit
    order["invoice_total_usd"] = q2(product + freight + surcharge - credit)


@bp.post("/salt/delivery-orders/<order_id>/deliver")
@auth("LogisticsPlanner")
def deliver_order(order_id):
    order = derive.get_order(order_id)
    contract = derive.get_contract(order["bid_contract_id"])
    _require_status(order, ("ALLOCATED", "SHORTED"))
    if contract["status"] != "ACTIVE":
        fail(ERR_CONTRACT_INVALID_STATE,
             "contract status %s does not admit a delivery" % contract["status"])
    if db.now() > order["required_by"]:
        fail(ERR_ORDER_INVALID_STATE,
             "the delivery deadline %s has already passed" % order["required_by"])

    for row in db.by_seq(derive.allocations_of_order(order["id"])):
        if row["state"] == "RESERVED":
            lot = alloc.consume_allocation(row)
            depot = store.depots.get(lot["depot_id"])
            if depot is not None:
                touch(depot)

    _invoice(order, contract)
    order["status"] = "DELIVERED"
    order["delivered_at"] = db.now()
    touch(order)
    touch(contract)
    return response.ok(serialize.order_json(order))


@bp.post("/salt/delivery-orders/<order_id>/waive-penalty")
@auth("ComplianceOfficer", "ContractAdministrator")
def waive_penalty(order_id):
    payload = body()
    require(payload, ["waiver_reason"])
    text(payload, "waiver_reason", minlen=1, maxlen=500)

    order = derive.get_order(order_id)
    contract = derive.get_contract(order["bid_contract_id"])
    if order["penalty_state"] != "ACCRUED":
        fail(ERR_PENALTY_NOT_ACCRUED,
             "penalty_state %s cannot be waived" % order["penalty_state"])

    order["penalty_state"] = "WAIVED"
    touch(order)
    touch(contract)
    return response.ok(serialize.order_json(order))
