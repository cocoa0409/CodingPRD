"""SpecialOrder endpoints."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, require_string, get_pagination, paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE
from services import public, public_list
from routes.inventory import make_inventory_item

bp = Blueprint("specialorders", __name__)


def _owner_check(role, user_id, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


@bp.route("/shop/special-orders", methods=["POST"])
def create_special_order():
    user_id, role = authenticate({"Customer"})
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise err(ERR_INVALID_REQUEST, "customer_id required")
    description = require_string(body, "description")
    product_id = body.get("product_id")
    deposit = body.get("deposit_cents", 0)
    if deposit is None:
        deposit = 0
    if isinstance(deposit, bool) or not isinstance(deposit, int) or deposit < 0:
        raise err(ERR_INVALID_REQUEST, "deposit_cents must be a non-negative integer")
    lookup(db.db.customers, customer_id)
    _owner_check(role, user_id, customer_id)
    if product_id is not None:
        lookup(db.db.products, product_id)
    so = base_fields()
    so.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "description": description,
        "deposit_cents": deposit,
        "status": "REQUESTED",
    })
    db.db.special_orders[so["id"]] = so
    return success(public(so), 201)


@bp.route("/shop/special-orders/<sid>", methods=["GET"])
def read_special_order(sid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    so = lookup(db.db.special_orders, sid)
    return success(public(so), 200)


@bp.route("/shop/special-orders", methods=["GET"])
def list_special_orders():
    authenticate({"Customer", "StoreClerk", "Manager"})
    limit, offset = get_pagination()
    items = list(db.db.special_orders.values())
    for key in ("customer_id", "product_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/special-orders/<sid>/start-sourcing", methods=["POST"])
def start_sourcing(sid):
    authenticate({"StoreClerk"})
    so = lookup(db.db.special_orders, sid)
    if so["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Special order is not REQUESTED")
    so["status"] = "SOURCING"
    touch(so)
    return success(public(so), 200)


@bp.route("/shop/special-orders/<sid>/mark-arrived", methods=["POST"])
def mark_arrived(sid):
    authenticate({"StoreClerk"})
    so = lookup(db.db.special_orders, sid)
    if so["status"] != "SOURCING":
        raise err(ERR_INVALID_STATE, "Special order is not SOURCING")
    so["status"] = "ARRIVED"
    if so["product_id"] is not None:
        product = db.db.products.get(so["product_id"])
        if product is not None:
            make_inventory_item(so["product_id"], False, "NM", None)
    touch(so)
    return success(public(so), 200)


@bp.route("/shop/special-orders/<sid>/fulfill", methods=["POST"])
def fulfill_special_order(sid):
    authenticate({"StoreClerk"})
    so = lookup(db.db.special_orders, sid)
    if so["status"] != "ARRIVED":
        raise err(ERR_INVALID_STATE, "Special order is not ARRIVED")
    so["status"] = "FULFILLED"
    touch(so)
    return success(public(so), 200)


@bp.route("/shop/special-orders/<sid>/cancel", methods=["POST"])
def cancel_special_order(sid):
    user_id, role = authenticate({"Customer"})
    so = lookup(db.db.special_orders, sid)
    _owner_check(role, user_id, so["customer_id"])
    if so["status"] not in ("REQUESTED", "SOURCING"):
        raise err(ERR_INVALID_STATE, "Special order cannot be cancelled")
    so["status"] = "CANCELLED"
    touch(so)
    return success(public(so), 200)
