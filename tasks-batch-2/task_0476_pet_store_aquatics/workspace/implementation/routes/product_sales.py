"""Point-of-sale product-sale endpoint (PRD §3.12)."""
from flask import Blueprint

import db
from db import touch
from clock import clock, parse_iso
from middleware import require_auth, require_role
from response import object_response
from errors import err
from services.common import (
    get_body, lookup, require_present, as_str, as_int,
)
from services.derive import compute_recall_state
from services.loyalty import accrue
from services.inventory import free_unit_sum, plan_allocation
from services.serialize import lot_out

bp = Blueprint("product_sales", __name__)


@bp.route("/product-sales", methods=["POST"])
def product_sale():
    _, role = require_auth()
    require_role(role, ["StoreClerk"])
    body = get_body()
    store_id = as_str(require_present(body, "store_id"), "store_id")
    product_id = as_str(require_present(body, "product_id"), "product_id")
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    store = lookup("stores", store_id)
    product = lookup("products", product_id)
    customer = lookup("customers", customer_id)
    quantity = as_int(require_present(body, "quantity"), "quantity")
    if quantity <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "quantity must be > 0.")
    redeem_points = 0
    if "redeem_points" in body and body["redeem_points"] is not None:
        redeem_points = as_int(body["redeem_points"], "redeem_points")
        if redeem_points < 0:
            raise err("ERR_INVALID_FIELD_VALUE", "redeem_points must be >= 0.")

    # Gate order (PRD §3.12): recall, then prescription, then redemption, then inventory.
    if compute_recall_state(product) != "CLEAR":
        raise err("ERR_PRODUCT_RECALLED")

    if product["is_prescription_diet"]:
        if not _has_valid_prescription(customer_id, product_id, quantity):
            raise err("ERR_PRESCRIPTION_REQUIRED")

    if redeem_points > customer["loyalty_points"]:
        raise err("ERR_INSUFFICIENT_LOYALTY_POINTS")

    if free_unit_sum(store_id, product_id) < quantity:
        raise err("ERR_INSUFFICIENT_INVENTORY")
    plan = plan_allocation(store_id, product_id, quantity)
    if plan is None:
        raise err("ERR_INSUFFICIENT_INVENTORY")

    # Allocate FEFO; decrement on-hand; deplete at 0.
    last_lot = None
    for lot, take in plan:
        lot["quantity_on_hand"] -= take
        if lot["quantity_on_hand"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        last_lot = lot

    # Charge = quantity*unit_price - redeemed value (points * store value).
    gross = quantity * product["unit_price_cents"]
    redeemed_value = redeem_points * store["loyalty_point_value_cents"]
    net_charge = gross - redeemed_value

    # loyalty_points -= redeem_points, then += earned.
    earned = quantity * product["loyalty_points_per_unit"]
    customer["loyalty_points"] -= redeem_points
    accrue(customer, net_charge, earned)
    touch(customer)

    return object_response(lot_out(last_lot), 201)


def _has_valid_prescription(customer_id, product_id, quantity):
    """An ACTIVE, non-expired prescription for (customer, product) whose
    max_units_per_order >= quantity (PRD §3.8)."""
    now = clock.now()
    for rx in db.prescriptions.values():
        if rx["customer_id"] != customer_id or rx["product_id"] != product_id:
            continue
        if rx["status"] != "ACTIVE":
            continue
        if parse_iso(rx["expires_at"]) <= now:
            continue
        if rx["max_units_per_order"] >= quantity:
            return True
    return False
