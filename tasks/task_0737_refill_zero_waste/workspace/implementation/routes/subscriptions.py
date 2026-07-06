from datetime import timedelta
from flask import Blueprint, request

import store
import response
import serialize
import calc
from errors import ApiError
from helpers import (endpoint, get_body, field, lookup, require_fk, stamp_new,
                     touch, paginate, owner_check)

bp = Blueprint("subscriptions", __name__)


@bp.post("/v1/subscriptions")
@endpoint(["Member", "StoreClerk"])
def create_subscription():
    body = get_body()
    member_id = field(body, "member_id", required=True, kind="str")
    product_id = field(body, "product_id", required=True, kind="str")
    station_id = field(body, "station_id", required=True, kind="str")
    target_net_g = field(body, "target_net_g", required=True, kind="int")
    interval_days = field(body, "interval_days", required=True, kind="int")
    owner_check(member_id)
    require_fk("members", member_id)
    require_fk("products", product_id)
    require_fk("stations", station_id)
    rec = {
        "member_id": member_id,
        "product_id": product_id,
        "station_id": station_id,
        "target_net_g": target_net_g,
        "interval_days": interval_days,
        "next_run_at": store.add_days(store.now(), interval_days),
        "last_run_order_id": None,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    store.DB["subscriptions"][rec["id"]] = rec
    return response.created(serialize.subscription_out(rec))


@bp.get("/v1/subscriptions/<subscription_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_subscription(subscription_id):
    return response.ok(serialize.subscription_out(lookup("subscriptions", subscription_id)))


@bp.get("/v1/subscriptions")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_subscriptions():
    filters = {
        "member_id": request.args.get("member_id"),
        "product_id": request.args.get("product_id"),
        "station_id": request.args.get("station_id"),
        "status": request.args.get("status"),
    }
    recs = list(store.DB["subscriptions"].values())
    for key, val in filters.items():
        if val is not None:
            recs = [s for s in recs if s[key] == val]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.subscription_out(s) for s in page], limit, offset, total)


@bp.post("/v1/subscriptions/<subscription_id>/run")
@endpoint(["Member", "StoreClerk"])
def run_subscription(subscription_id):
    sub = lookup("subscriptions", subscription_id)
    body = get_body()
    expected = field(body, "expected_subscription_version", required=True, kind="int")
    owner_check(sub["member_id"])
    # State (priority 4) beats OCC (priority 10)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "subscription must be ACTIVE to run")
    if expected != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", "subscription version has advanced")

    member = store.DB["members"][sub["member_id"]]
    product = store.DB["products"][sub["product_id"]]
    now = store.now()

    order = {
        "member_id": sub["member_id"],
        "station_id": sub["station_id"],
        "fulfillment_channel": "DELIVERY",
        "fill_window_start_at": now,
        "fill_window_end_at": now + timedelta(hours=1),
        "fulfillment_status": "CART",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "deposit_total_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "loyalty_points_earned": 0,
    }
    stamp_new(order)
    store.DB["orders"][order["id"]] = order

    net = sub["target_net_g"]
    line = {
        "order_id": order["id"],
        "product_id": sub["product_id"],
        "container_id": None,
        "bin_id": None,
        "declared_tare_g": 0,
        "estimated_gross_g": net,
        "gross_weight_g": None,
        "net_weight_g": net,
        "line_price_cents": calc.refill_line_price(net, product, member["membership_tier"]),
        "pricing_stage": "PROVISIONAL",
    }
    stamp_new(line)
    store.DB["lines"][line["id"]] = line

    sub["last_run_order_id"] = order["id"]
    sub["next_run_at"] = store.add_days(now, sub["interval_days"])
    touch(sub)  # increments version by 1

    return response.created(serialize.order_out(order))


@bp.post("/v1/subscriptions/<subscription_id>/cancel")
@endpoint(["Member", "StoreClerk"])
def cancel_subscription(subscription_id):
    sub = lookup("subscriptions", subscription_id)
    owner_check(sub["member_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "subscription must be ACTIVE to cancel")
    sub["status"] = "CANCELLED"
    touch(sub)
    return response.ok(serialize.subscription_out(sub))
