"""Customer routes."""
from flask import Blueprint, request
from middleware import require_role
from db import store, new_id
from response import success_object, success_list
from serializers import customer_view
from services.lazy import recompute_standing
from routes.common import (
    get_json_body, parse_str_field, get_shop_or_404, get_customer_or_404,
    get_pagination, paginate,
)

bp = Blueprint("customers", __name__)


@bp.route("/shops/<shopId>/customers", methods=["POST"])
def create_customer(shopId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    body = get_json_body()
    company_name = parse_str_field(body, "company_name", required=True)
    now = store.now()
    c = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "shop_id": shopId,
        "company_name": company_name,
        "account_credit_cents": 0,
        "standing": "GOOD",
    }
    store.customers[c["id"]] = c
    return success_object(customer_view(c), status=201)


def _list_customers(shop_id_filter):
    items = list(store.customers.values())
    if shop_id_filter is not None:
        items = [c for c in items if c["shop_id"] == shop_id_filter]
    standing = request.args.get("standing")
    if standing:
        items = [c for c in items if c["standing"] == standing]
    items.sort(key=lambda c: c["created_at"])
    return items


@bp.route("/shops/<shopId>/customers", methods=["GET"])
def list_customers(shopId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    get_shop_or_404(shopId)
    limit, offset = get_pagination()
    items = _list_customers(shopId)
    page, total = paginate(items, limit, offset)
    return success_list([customer_view(c) for c in page], limit, offset, total)


@bp.route("/shops/<shopId>/customers/<customerId>", methods=["GET"])
def get_customer(shopId, customerId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    c = get_customer_or_404(customerId, shopId)
    recompute_standing(c["id"])
    return success_object(customer_view(c))


# Flat aliases
@bp.route("/shops/customers", methods=["GET"])
def list_customers_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    shop_id = request.args.get("shop_id")
    items = _list_customers(shop_id)
    page, total = paginate(items, limit, offset)
    return success_list([customer_view(c) for c in page], limit, offset, total)


@bp.route("/shops/customers/<customerId>", methods=["GET"])
def get_customer_flat(customerId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    c = get_customer_or_404(customerId)
    recompute_standing(c["id"])
    return success_object(customer_view(c))
