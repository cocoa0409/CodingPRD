"""SpecialOrder endpoints (PRD §3.11)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from db import stamp_create, touch
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
from services.serialize import special_order_out

bp = Blueprint("special_orders", __name__)

READ_ROLES = ["InventoryManager", "StoreClerk", "Customer"]


def _owner_guard(role, user_id, order):
    if role == "Customer" and order["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER")


@bp.route("/special-orders", methods=["POST"])
def request_order():
    _, role = require_auth()
    require_role(role, ["Customer", "StoreClerk"])
    body = get_body()
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    product_id = as_str(require_present(body, "product_id"), "product_id")
    store_id = as_str(require_present(body, "store_id"), "store_id")
    customer = lookup("customers", customer_id)
    product = lookup("products", product_id)
    lookup("stores", store_id)
    quantity = as_int(require_present(body, "quantity"), "quantity")
    if quantity <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "quantity must be > 0.")
    deposit_pct = 0.25
    if "deposit_pct" in body and body["deposit_pct"] is not None:
        deposit_pct = as_number(body["deposit_pct"], "deposit_pct")
        if deposit_pct < 0.0 or deposit_pct > 1.0:
            raise err("ERR_INVALID_FIELD_VALUE", "deposit_pct must be in [0.0, 1.0].")

    # special_order_total (PRD §3.11): tier discount per unit, round per unit,
    # then sum. tier_disc read at request time, frozen on the order.
    tier = compute_loyalty_tier(customer["lifetime_spend_cents"])
    tier_disc = TIER_DISCOUNT[tier]
    unit_price = product["unit_price_cents"]
    per_unit_net = round_half_up(Decimal(unit_price) * (Decimal("1") - tier_disc))
    gross_net_cents = per_unit_net * quantity
    deposit_cents = round_half_up(Decimal(gross_net_cents) * Decimal(str(deposit_pct)))
    balance_cents = gross_net_cents - deposit_cents

    record = {
        "customer_id": customer_id,
        "product_id": product_id,
        "store_id": store_id,
        "quantity": quantity,
        "deposit_pct": deposit_pct,
        "deposit_cents": deposit_cents,
        "balance_cents": balance_cents,
        "status": "REQUESTED",
    }
    stamp_create(record)
    db.special_orders[record["id"]] = record
    return object_response(special_order_out(record), 201)


@bp.route("/special-orders", methods=["GET"])
def list_orders():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.special_orders.values())
    for field in ("customer_id", "product_id", "store_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([special_order_out(r) for r in page], limit, offset, total)


@bp.route("/special-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("special_orders", order_id)
    return object_response(special_order_out(record))


@bp.route("/special-orders/<order_id>/allocate", methods=["POST"])
def allocate(order_id):
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    order = lookup("special_orders", order_id)
    if order["status"] != "REQUESTED":
        raise err("ERR_SPECIAL_ORDER_STATE_INVALID")
    product = db.products[order["product_id"]]
    if compute_recall_state(product) != "CLEAR":
        raise err("ERR_PRODUCT_RECALLED")

    store_id = order["store_id"]
    product_id = order["product_id"]
    quantity = order["quantity"]
    if free_unit_sum(store_id, product_id) < quantity:
        raise err("ERR_INSUFFICIENT_INVENTORY")
    plan = plan_allocation(store_id, product_id, quantity)
    if plan is None:
        raise err("ERR_INSUFFICIENT_INVENTORY")

    # Reserve units FEFO; record the reservation per lot for fulfill/cancel.
    reservations = {}
    for lot, take in plan:
        lot["quantity_reserved"] += take
        touch(lot)
        reservations[lot["id"]] = reservations.get(lot["id"], 0) + take
    order["_reservations"] = reservations
    order["status"] = "ALLOCATED"
    touch(order)
    return object_response(special_order_out(order))


@bp.route("/special-orders/<order_id>/fulfill", methods=["POST"])
def fulfill(order_id):
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    order = lookup("special_orders", order_id)
    if order["status"] != "ALLOCATED":
        raise err("ERR_SPECIAL_ORDER_STATE_INVALID")
    product = db.products[order["product_id"]]
    if compute_recall_state(product) != "CLEAR":
        raise err("ERR_PRODUCT_RECALLED")

    # Consume reserved units: reserved -= n, on_hand -= n, deplete at 0.
    reservations = order.get("_reservations", {})
    for lot_id, n in reservations.items():
        lot = db.inventory_lots.get(lot_id)
        if lot is None:
            continue
        lot["quantity_reserved"] -= n
        lot["quantity_on_hand"] -= n
        if lot["quantity_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    order["_reservations"] = {}
    order["status"] = "FULFILLED"

    # Charge the full order: deposit + balance.
    customer = db.customers[order["customer_id"]]
    net = order["deposit_cents"] + order["balance_cents"]
    earned = whole_dollar_points(net)
    accrue(customer, net, earned)
    touch(customer)

    touch(order)
    return object_response(special_order_out(order))


@bp.route("/special-orders/<order_id>/cancel", methods=["POST"])
def cancel(order_id):
    user_id, role = require_auth()
    require_role(role, ["Customer"])
    order = lookup("special_orders", order_id)
    _owner_guard(role, user_id, order)
    if order["status"] not in ("REQUESTED", "ALLOCATED"):
        raise err("ERR_SPECIAL_ORDER_STATE_INVALID")

    # Cancelling an ALLOCATED order releases reservations.
    if order["status"] == "ALLOCATED":
        reservations = order.get("_reservations", {})
        for lot_id, n in reservations.items():
            lot = db.inventory_lots.get(lot_id)
            if lot is None:
                continue
            lot["quantity_reserved"] -= n
            touch(lot)
        order["_reservations"] = {}

    order["status"] = "CANCELLED"
    touch(order)
    return object_response(special_order_out(order))
