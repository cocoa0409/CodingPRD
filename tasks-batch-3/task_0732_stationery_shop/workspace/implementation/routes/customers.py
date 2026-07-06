"""Customer endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import util

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin"])
    body = util.get_body()
    email = util.get_str(body, "email")
    full_name = util.get_str(body, "full_name")
    phone = util.get_str(body, "phone")
    # Enforce email uniqueness
    for c in db.customers.values():
        if c["email"] == email:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "email must be unique")
    c = models.make_common({
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "credit_balance_cents": 0,
        "cumulative_deposits_paid_cents": 0,
    })
    db.customers[c["id"]] = c
    return resp.created(c)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = middleware.get_auth()
    c = models.get_customer(cid)
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    if role == "Customer":
        middleware.require_owner(user_id, c["id"])
    return resp.ok(c)


@bp.route("/customers/<cid>/designs", methods=["GET"])
def list_customer_designs(cid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    c = models.get_customer(cid)
    if role == "Customer":
        middleware.require_owner(user_id, c["id"])
    limit, offset = util.get_pagination()
    items = [d for d in db.designs.values() if d["customer_id"] == cid]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


@bp.route("/customers/<cid>/orders", methods=["GET"])
def list_customer_orders(cid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    c = models.get_customer(cid)
    if role == "Customer":
        middleware.require_owner(user_id, c["id"])
    limit, offset = util.get_pagination()
    status_filter = request.args.get("status")
    items = [o for o in db.orders.values() if o["customer_id"] == cid]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
