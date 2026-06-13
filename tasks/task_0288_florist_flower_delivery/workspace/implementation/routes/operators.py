"""Test-driving operator routes: simulated clock, forced payment auth, and
loyalty/wallet injection (PRD §2.10, §3.1, §3.4)."""
from flask import Blueprint

import errors
from db import store
from middleware import require_auth, require_role
from helpers import get_body, touch, public, require_fields, as_int, as_str, as_enum
from response import success
from services import clock

bp = Blueprint("operators", __name__)

TIERS = {"STANDARD", "SILVER", "GOLD"}


def _public_clock():
    return {
        "id": store.clock["id"],
        "created_at": store.clock["created_at"],
        "current_utc": store.clock["current_utc"],
    }


@bp.route("/floral/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    clock.set_clock(body["to_iso8601"])
    return success(_public_clock())


@bp.route("/floral/_clock", methods=["GET"])
def get_clock():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer", "Florist"})
    return success(_public_clock())


@bp.route("/floral/_payments/mark_authorized", methods=["POST"])
def mark_authorized():
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["order_id"])
    order_id = as_str(body, "order_id")
    order = store.orders.get(order_id)
    if order is None:
        raise errors.not_found("order_id not found")
    if order["payment_status"] != "UNPAID":
        raise errors.invalid_state("Payment is not in UNPAID state")
    order["_authorized_amount_cents"] = order["estimated_total_cents"]
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(public(order))


@bp.route("/floral/_inject/set_loyalty_tier", methods=["POST"])
def set_loyalty_tier():
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["customer_id", "loyalty_tier"])
    customer_id = as_str(body, "customer_id")
    loyalty_tier = as_enum(body, "loyalty_tier", TIERS)
    customer = store.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("customer_id not found")
    customer["loyalty_tier"] = loyalty_tier
    touch(customer)
    return success(public(customer))


@bp.route("/floral/_inject/credit_wallet", methods=["POST"])
def credit_wallet():
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["customer_id", "amount_cents"])
    customer_id = as_str(body, "customer_id")
    amount_cents = as_int(body, "amount_cents")
    customer = store.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("customer_id not found")
    customer["wallet_credit_cents"] += amount_cents
    touch(customer)
    return success(public(customer))
