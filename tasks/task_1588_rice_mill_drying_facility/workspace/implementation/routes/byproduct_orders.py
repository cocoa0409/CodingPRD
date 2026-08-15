"""ByproductSaleOrder endpoints (PRD §3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_ORDER_INVALID_STATE, ERR_INSUFFICIENT_BYPRODUCT_INVENTORY,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import D, q2, new_id, next_seq
from validate import get_body, req_str, req_enum, req_num, req_int

bp = Blueprint("byproduct_orders", __name__)


@bp.route("/mill/byproduct-orders", methods=["POST"])
def create_order():
    authorized(["Merchandiser"])
    body = get_body()
    season_id = req_str(body, "season_id")
    product = req_enum(body, "product", core.BYPRODUCT_PRODUCTS)
    quantity = req_num(body, "quantity_cwt", positive=True)
    price = req_int(body, "price_cents_per_cwt")
    buyer = req_str(body, "buyer_name")
    require_resource("seasons", season_id)
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "product": product,
        "quantity_cwt": q2(quantity),
        "price_cents_per_cwt": price,
        "buyer_name": buyer,
        "status": "OPEN",
    }
    core.touch_new(rec)
    db["byproduct_orders"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/byproduct-orders", methods=["GET"])
def list_orders():
    return list_endpoint("byproduct_orders", ["season_id", "product", "status"])


@bp.route("/mill/byproduct-orders/<rid>", methods=["GET"])
def get_order(rid):
    return get_endpoint("byproduct_orders", rid)


def _get_order_for_action(rid):
    authorized(["Merchandiser"])
    return require_resource("byproduct_orders", rid)


@bp.route("/mill/byproduct-orders/<rid>/reserve", methods=["POST"])
def reserve_order(rid):
    order = _get_order_for_action(rid)
    if order["status"] != "OPEN":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"reserve requires OPEN; order is {order['status']}")
    inv = core.season_inventory(order["season_id"])
    if D(inv[order["product"]]["available_cwt"]) < D(order["quantity_cwt"]):
        raise_error(ERR_INSUFFICIENT_BYPRODUCT_INVENTORY,
                    "available inventory cannot cover the reserved quantity")
    order["status"] = "RESERVED"
    core.bump(order)
    return success_object(public(order))


@bp.route("/mill/byproduct-orders/<rid>/release", methods=["POST"])
def release_order(rid):
    order = _get_order_for_action(rid)
    if order["status"] != "RESERVED":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"release requires RESERVED; order is {order['status']}")
    order["status"] = "OPEN"
    core.bump(order)
    return success_object(public(order))


@bp.route("/mill/byproduct-orders/<rid>/ship", methods=["POST"])
def ship_order(rid):
    order = _get_order_for_action(rid)
    if order["status"] != "RESERVED":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"ship requires RESERVED; order is {order['status']}")
    order["status"] = "SHIPPED"
    core.bump(order)
    return success_object(public(order))


@bp.route("/mill/byproduct-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    order = _get_order_for_action(rid)
    if order["status"] not in ("OPEN", "RESERVED"):
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"cancel requires OPEN or RESERVED; order is {order['status']}")
    order["status"] = "CANCELLED"
    core.bump(order)
    return success_object(public(order))
