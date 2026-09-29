"""Manual reservations and single-line releases."""

from flask import Blueprint

import db
import response
from db import store, touch
from errors import (
    ERR_ALLOCATION_NOT_RESERVED,
    ERR_DEPOT_CLOSED,
    ERR_INSUFFICIENT_LOT_TONS,
    ERR_LOT_QUARANTINED,
    ERR_ORDER_INVALID_STATE,
    ERR_PRODUCT_LINE_MISMATCH,
    ERR_STALE_STOCKPILE_LOT_VERSION,
    fail,
)
from middleware import auth
from services import alloc, derive, serialize
from util import D, body, filter_str, number, require

bp = Blueprint("allocations", __name__)


def _sync_order(order):
    allocated = derive.order_allocated_tons(order["id"])
    if order["status"] == "REQUESTED" and D(allocated) >= D(order["requested_tons"]):
        order["status"] = "ALLOCATED"
    elif order["status"] == "ALLOCATED" and D(allocated) < D(order["requested_tons"]):
        order["status"] = "REQUESTED"
    touch(order)


@bp.post("/salt/allocations")
@auth("LogisticsPlanner")
def create_allocation():
    payload = body()
    require(payload, ["delivery_order_id", "stockpile_lot_id", "tons",
                      "expected_stockpile_lot_version"])
    tons = number(payload, "tons", gt=0)

    order = derive.get_order(payload["delivery_order_id"])
    lot = derive.get_lot(payload["stockpile_lot_id"])
    contract = derive.get_contract(order["bid_contract_id"])

    if payload["expected_stockpile_lot_version"] != lot["version"]:
        fail(ERR_STALE_STOCKPILE_LOT_VERSION,
             "expected_stockpile_lot_version %s does not match the lot's %s"
             % (payload["expected_stockpile_lot_version"], lot["version"]))
    if order["status"] not in ("REQUESTED", "ALLOCATED", "SHORTED"):
        fail(ERR_ORDER_INVALID_STATE,
             "order status %s does not admit a manual reservation" % order["status"])
    if lot["lot_state"] == "QUARANTINED":
        fail(ERR_LOT_QUARANTINED, "the lot is quarantined")

    depot = derive.get_depot(lot["depot_id"])
    if depot["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the holding depot is closed")
    if lot["product_line"] != contract["product_line"]:
        fail(ERR_PRODUCT_LINE_MISMATCH,
             "lot product_line %s does not match the contract's %s"
             % (lot["product_line"], contract["product_line"]))
    if depot["state_code"] != contract["state_code"]:
        fail(ERR_PRODUCT_LINE_MISMATCH,
             "the holding depot's state_code %s does not match the contract's %s"
             % (depot["state_code"], contract["state_code"]))
    if derive.lot_available_tons(lot) < D(tons):
        fail(ERR_INSUFFICIENT_LOT_TONS,
             "the lot has %s tons available" % derive.lot_available_tons(lot))

    allocation = alloc.new_allocation(order, lot, tons, "MANUAL", 1)
    _sync_order(order)
    touch(contract)
    return response.created(serialize.allocation_json(allocation))


@bp.get("/salt/allocations/<allocation_id>")
@auth()
def read_allocation(allocation_id):
    return response.ok(
        serialize.allocation_json(derive.get_allocation(allocation_id)))


@bp.get("/salt/allocations")
@auth()
def list_allocations():
    rows = list(store.allocations.values())
    for name in ("delivery_order_id", "stockpile_lot_id", "state", "origin"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.allocation_json)


@bp.post("/salt/allocations/<allocation_id>/release")
@auth("LogisticsPlanner")
def release_allocation(allocation_id):
    allocation = derive.get_allocation(allocation_id)
    if allocation["state"] != "RESERVED":
        fail(ERR_ALLOCATION_NOT_RESERVED,
             "allocation state %s is not RESERVED" % allocation["state"])
    alloc.release_allocation(allocation)
    order = derive.get_order(allocation["delivery_order_id"])
    _sync_order(order)
    return response.ok(serialize.allocation_json(allocation))
