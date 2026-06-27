"""Subscription + Shipment endpoints (PRD §3.10)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import stamp_create, touch
from clock import clock, parse_iso
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_number, round_half_up, TIER_DISCOUNT,
)
from services.derive import compute_loyalty_tier, compute_recall_state
from services.loyalty import whole_dollar_points, accrue
from services.inventory import free_unit_sum, plan_allocation
from services.serialize import subscription_out, shipment_out

bp = Blueprint("subscriptions", __name__)

SUB_READ_ROLES = ["InventoryManager", "StoreClerk", "Customer"]
SHIP_READ_ROLES = ["InventoryManager", "StoreClerk", "Customer"]


def _owner_guard(role, user_id, subscription):
    """Customer ownership check (PRD §2.1, precedence step 3)."""
    if role == "Customer" and subscription["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER")


@bp.route("/subscriptions", methods=["POST"])
def create_subscription():
    _, role = require_auth()
    require_role(role, ["Customer", "StoreClerk"])
    body = get_body()
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    product_id = as_str(require_present(body, "product_id"), "product_id")
    store_id = as_str(require_present(body, "store_id"), "store_id")
    lookup("customers", customer_id)
    lookup("products", product_id)
    lookup("stores", store_id)
    qpc = as_int(require_present(body, "quantity_per_cycle"), "quantity_per_cycle")
    if qpc <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "quantity_per_cycle must be > 0.")
    cycle_days = as_int(require_present(body, "cycle_days"), "cycle_days")
    if cycle_days <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "cycle_days must be > 0.")
    discount_pct = 0.0
    if "discount_pct" in body and body["discount_pct"] is not None:
        discount_pct = as_number(body["discount_pct"], "discount_pct")
        if discount_pct < 0.0 or discount_pct > 0.5:
            raise err("ERR_INVALID_FIELD_VALUE", "discount_pct must be in [0.0, 0.5].")
    next_ship_at = require_present(body, "next_ship_at")
    parse_iso(next_ship_at)  # validate format

    record = {
        "customer_id": customer_id,
        "product_id": product_id,
        "store_id": store_id,
        "quantity_per_cycle": qpc,
        "cycle_days": cycle_days,
        "discount_pct": discount_pct,
        "next_ship_at": next_ship_at,
        "shipments_count": 0,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.subscriptions[record["id"]] = record
    return object_response(subscription_out(record), 201)


@bp.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    _, role = require_auth()
    require_role(role, SUB_READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.subscriptions.values())
    for field in ("customer_id", "product_id", "store_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([subscription_out(r) for r in page], limit, offset, total)


@bp.route("/subscriptions/<sub_id>", methods=["GET"])
def get_subscription(sub_id):
    _, role = require_auth()
    require_role(role, SUB_READ_ROLES)
    record = lookup("subscriptions", sub_id)
    return object_response(subscription_out(record))


@bp.route("/subscriptions/<sub_id>/pause", methods=["POST"])
def pause(sub_id):
    user_id, role = require_auth()
    require_role(role, ["Customer"])
    sub = lookup("subscriptions", sub_id)
    _owner_guard(role, user_id, sub)
    if sub["status"] != "ACTIVE":
        raise err("ERR_SUBSCRIPTION_STATE_INVALID")
    sub["status"] = "PAUSED"
    touch(sub)
    return object_response(subscription_out(sub))


@bp.route("/subscriptions/<sub_id>/resume", methods=["POST"])
def resume(sub_id):
    user_id, role = require_auth()
    require_role(role, ["Customer"])
    sub = lookup("subscriptions", sub_id)
    _owner_guard(role, user_id, sub)
    if sub["status"] != "PAUSED":
        raise err("ERR_SUBSCRIPTION_STATE_INVALID")
    product = db.products[sub["product_id"]]
    if compute_recall_state(product) != "CLEAR":
        raise err("ERR_PRODUCT_RECALLED")
    sub["status"] = "ACTIVE"
    sub["next_ship_at"] = _iso(clock.now() + timedelta(days=sub["cycle_days"]))
    touch(sub)
    return object_response(subscription_out(sub))


@bp.route("/subscriptions/<sub_id>/cancel", methods=["POST"])
def cancel(sub_id):
    user_id, role = require_auth()
    require_role(role, ["Customer"])
    sub = lookup("subscriptions", sub_id)
    _owner_guard(role, user_id, sub)
    if sub["status"] not in ("ACTIVE", "PAUSED", "HALTED"):
        raise err("ERR_SUBSCRIPTION_STATE_INVALID")
    sub["status"] = "CANCELLED"
    touch(sub)
    return object_response(subscription_out(sub))


@bp.route("/subscriptions/<sub_id>/run-shipment", methods=["POST"])
def run_shipment(sub_id):
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    sub = lookup("subscriptions", sub_id)
    body = get_body()
    expected = as_int(require_present(body, "expected_subscription_version"), "expected_subscription_version")

    # Ordered checks (PRD §3.10): status, then OCC, then due, then recall, then inventory.
    if sub["status"] != "ACTIVE":
        raise err("ERR_SUBSCRIPTION_STATE_INVALID")
    if expected != sub["version"]:
        raise err("ERR_STALE_VERSION")
    if clock.now() < parse_iso(sub["next_ship_at"]):
        raise err("ERR_SHIPMENT_NOT_DUE")
    product = db.products[sub["product_id"]]
    if compute_recall_state(product) != "CLEAR":
        raise err("ERR_PRODUCT_RECALLED")

    units = sub["quantity_per_cycle"]
    store_id = sub["store_id"]
    product_id = sub["product_id"]
    if free_unit_sum(store_id, product_id) < units:
        raise err("ERR_INSUFFICIENT_INVENTORY")
    plan = plan_allocation(store_id, product_id, units)
    if plan is None:
        raise err("ERR_INSUFFICIENT_INVENTORY")

    # auto_ship_charge (PRD §3.10): compose multiplicatively on the gross sum,
    # base first then tier, single rounding at the end.
    unit_price = product["unit_price_cents"]
    gross_cents = units * unit_price
    customer = db.customers[sub["customer_id"]]
    tier = compute_loyalty_tier(customer["lifetime_spend_cents"])
    base_disc = Decimal(str(sub["discount_pct"]))
    tier_disc = TIER_DISCOUNT[tier]
    after_base = Decimal(gross_cents) * (Decimal("1") - base_disc)
    after_tier = after_base * (Decimal("1") - tier_disc)
    net_cents = round_half_up(after_tier)

    # Allocate FEFO; decrement on-hand; deplete at 0; bump each drawn lot.
    last_lot_id = None
    for lot, take in plan:
        lot["quantity_on_hand"] -= take
        if lot["quantity_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        last_lot_id = lot["id"]

    # Create the Shipment record (FULFILLED).
    shipment = {
        "subscription_id": sub_id,
        "lot_id": last_lot_id,
        "units": units,
        "gross_cents": gross_cents,
        "net_cents": net_cents,
        "status": "FULFILLED",
    }
    stamp_create(shipment)
    db.shipments[shipment["id"]] = shipment

    # Charge the customer.
    earned = whole_dollar_points(net_cents)
    accrue(customer, net_cents, earned)
    touch(customer)

    # Advance subscription.
    sub["shipments_count"] += 1
    sub["next_ship_at"] = _iso(parse_iso(sub["next_ship_at"]) + timedelta(days=sub["cycle_days"]))
    touch(sub)

    return object_response(shipment_out(shipment), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    _, role = require_auth()
    require_role(role, SHIP_READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.shipments.values())
    for field in ("subscription_id", "lot_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([shipment_out(r) for r in page], limit, offset, total)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    _, role = require_auth()
    require_role(role, SHIP_READ_ROLES)
    record = lookup("shipments", shipment_id)
    return object_response(shipment_out(record))


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
