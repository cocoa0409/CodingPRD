"""Buy-out orders (PRD 3.7)."""

from flask import Blueprint

import auth
import boxops
import constants as K
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("buyouts", __name__)


@bp.get("/kidswear/buy-out-orders")
def list_orders():
    caller = auth.gate("Member", "BillingAgent", "PlatformAdmin", "WarehouseOperator")
    rows = store.all_rows("buyout_orders")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "box_item_id", shape.query_str("box_item_id"))
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.BUYOUT_STATUSES))
    return envelope.listing(rows, serialize.buyout_order)


@bp.get("/kidswear/buy-out-orders/<buy_out_order_id>")
def read_order(buy_out_order_id):
    caller = auth.gate("Member", "BillingAgent", "PlatformAdmin", "WarehouseOperator")
    row = lookup.buyout_order(buy_out_order_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.buyout_order(row))


@bp.post("/kidswear/buy-out-orders/<buy_out_order_id>/accept")
def accept_order(buy_out_order_id):
    caller = auth.gate("Member")
    order = lookup.buyout_order(buy_out_order_id)
    auth.own(caller, order["member_id"])
    member = lookup.member(order["member_id"])
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_r(member)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE")
    clock = timeutil.now()
    if clock >= order["quote_expires_at"]:
        raise ApiError("ERR_BUYOUT_QUOTE_EXPIRED")
    item = lookup.box_item(order["box_item_id"])
    if item["embargo_until"] is not None and clock < item["embargo_until"]:
        raise ApiError("ERR_CAPSULE_EMBARGOED")
    order["status"] = "ACCEPTED"
    store.touch(order)
    return envelope.ok(serialize.buyout_order(order))


@bp.post("/kidswear/buy-out-orders/<buy_out_order_id>/pay")
def pay_order(buy_out_order_id):
    auth.gate("BillingAgent")
    order = lookup.buyout_order(buy_out_order_id)
    member = lookup.member(order["member_id"])
    lookup.standing(member, block_pending=True)
    if order["status"] == "ACCEPTED":
        order["status"] = "PAID"
        store.touch(order)
        ledger.new_charge(member, "BUYOUT_PRICE", order["final_price_cents"], None)
        return envelope.ok(serialize.buyout_order(order))
    if order["status"] == "PAID":
        item = lookup.box_item(order["box_item_id"])
        item["settlement_status"] = "BOUGHT_OUT"
        item["fulfillment_status"] = "RECEIVED"
        store.touch(item)
        unit = store.get("units", item["unit_id"])
        if unit is not None and unit["state"] == "OUT":
            unit["state"] = "SOLD"
            store.touch(unit)
        member["permanent_slots_consumed"] += 1
        store.touch(member)
        order["status"] = "COMPLETED"
        store.touch(order)
        box = boxops.box_of_item(item)
        if box is not None:
            boxops.maybe_close_box(box)
        return envelope.ok(serialize.buyout_order(order))
    raise ApiError("ERR_INVALID_STATE")


@bp.post("/kidswear/buy-out-orders/<buy_out_order_id>/cancel")
def cancel_order(buy_out_order_id):
    caller = auth.gate("Member")
    order = lookup.buyout_order(buy_out_order_id)
    auth.own(caller, order["member_id"])
    member = lookup.member(order["member_id"])
    lookup.standing(member, block_pending=True)
    if order["status"] not in ("QUOTED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE")
    order["status"] = "CANCELLED"
    store.touch(order)
    return envelope.ok(serialize.buyout_order(order))


@bp.post("/kidswear/buy-out-orders/<buy_out_order_id>/expire")
def expire_order(buy_out_order_id):
    auth.gate("BillingAgent")
    order = lookup.buyout_order(buy_out_order_id)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE")
    if timeutil.now() < order["quote_expires_at"]:
        raise ApiError("ERR_INVALID_STATE", "The quote's TTL has not elapsed.")
    order["status"] = "EXPIRED"
    store.touch(order)
    return envelope.ok(serialize.buyout_order(order))
