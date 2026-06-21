"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_str, parse_pagination, paginate, bool_arg
from services.lookups import get_shop, get_customer

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@endpoint("ShopManager")
def create_customer():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    shop = get_shop(shop_id)
    name = require_str(body, "name")
    email = require_str(body, "email")

    # email unique among the shop's non-archived customers (PRD §3.1).
    for c in store.customers.values():
        if c["shop_id"] == shop_id and not c["archived"] and c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already in use for this shop")

    cust = new_common_fields()
    cust.update({
        "shop_id": shop_id,
        "name": name,
        "email": email,
        "outstanding_deposit_cents": 0,
        "archived": False,
    })
    store.customers[cust["id"]] = cust
    return success(view(cust), status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_customer_route(customer_id):
    cust = get_customer(customer_id)
    return success(view(cust), status=200)


@bp.route("/customers/<customer_id>/archive", methods=["POST"])
@endpoint("ShopManager")
def archive_customer(customer_id):
    cust = get_customer(customer_id)
    cust["archived"] = True
    touch(cust)
    return success(view(cust), status=200)


@bp.route("/customers", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_customers():
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    include_archived = bool_arg("include_archived", default=False)
    items = list(store.customers.values())
    if shop_id is not None:
        items = [c for c in items if c["shop_id"] == shop_id]
    if not include_archived:
        items = [c for c in items if not c["archived"]]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)
