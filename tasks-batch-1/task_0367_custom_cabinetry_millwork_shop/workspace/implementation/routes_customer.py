"""Customer routes."""
from flask import Blueprint

from db import store
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_bool,
                     parse_pagination, paginate, sort_by_created)
from models import _base_record, touch, serialize_customer
from lookups import get_shop, get_customer_in_shop

bp = Blueprint("customer", __name__)


@bp.route("/shops/<shop_id>/customers", methods=["POST"])
def create_customer(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_shop(shop_id)
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")

    rec = _base_record()
    rec.update({
        "shop_id": shop_id,
        "full_name": full_name,
        "email": email,
        "credit_hold": False,
    })
    store.customers[rec["id"]] = rec
    return success(serialize_customer(rec), 201)


@bp.route("/shops/<shop_id>/customers/<customer_id>", methods=["GET"])
def get_customer(shop_id, customer_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Customer"})
    c = get_customer_in_shop(shop_id, customer_id)
    return success(serialize_customer(c), 200)


@bp.route("/shops/<shop_id>/customers/<customer_id>", methods=["PATCH"])
def update_customer(shop_id, customer_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    c = get_customer_in_shop(shop_id, customer_id)
    body = get_body()
    credit_hold = require_bool(body, "credit_hold")
    c["credit_hold"] = credit_hold
    touch(c)
    return success(serialize_customer(c), 200)


@bp.route("/shops/<shop_id>/customers", methods=["GET"])
def list_customers(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_shop(shop_id)
    limit, offset = parse_pagination()
    items = [c for c in store.customers.values() if c["shop_id"] == shop_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_customer(c) for c in page], limit, offset, total)
