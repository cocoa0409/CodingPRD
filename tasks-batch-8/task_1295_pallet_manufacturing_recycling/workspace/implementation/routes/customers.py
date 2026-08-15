"""Customer endpoints: register/list/get/suspend/reinstate/close."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, as_str,
)
from response import success
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation, get_or_404,
)

bp = Blueprint("customers", __name__)

OPEN_ORDER_STATES = ("DRAFT", "CONFIRMED", "ALLOCATED", "SHIPPED")


@bp.post("/pallet-ops/customers")
def create_customer():
    require_roles("SalesRep")
    body = get_json_body()
    company_name = as_str(req_field(body, "company_name"), "company_name")
    if any(c["company_name"] == company_name for c in db.customers.values()):
        raise_err("ERR_INVALID_REQUEST", "company_name must be unique: %s" % company_name)

    customer = {
        "company_name": company_name,
        "pool_credit_balance_cents": 0,
        "pool_units_outstanding": 0,
        "credit_hold": False,
        "status": "ACTIVE",
    }
    init_common(customer)
    db.customers[customer["id"]] = customer
    return success(serialize(customer), status=201)


@bp.get("/pallet-ops/customers")
def list_customers():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.customers.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/customers/<cid>")
def get_customer(cid):
    require_roles()
    customer = get_or_404(db.customers, cid, "Customer")
    return success(serialize(customer))


@bp.post("/pallet-ops/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles("SalesRep")
    customer = get_or_404(db.customers, cid, "Customer")
    if customer["status"] != "ACTIVE":
        raise_err("ERR_CUSTOMER_NOT_ACTIVE", "suspend requires customer ACTIVE")
    customer["status"] = "SUSPENDED"
    customer["credit_hold"] = True
    touch(customer)
    return success(serialize(customer))


@bp.post("/pallet-ops/customers/<cid>/reinstate")
def reinstate_customer(cid):
    require_roles("SalesRep")
    customer = get_or_404(db.customers, cid, "Customer")
    if customer["status"] != "SUSPENDED":
        raise_err("ERR_CUSTOMER_NOT_SUSPENDED", "reinstate requires customer SUSPENDED")
    customer["status"] = "ACTIVE"
    customer["credit_hold"] = False
    touch(customer)
    return success(serialize(customer))


@bp.post("/pallet-ops/customers/<cid>/close")
def close_customer(cid):
    require_roles("SalesRep")
    customer = get_or_404(db.customers, cid, "Customer")
    if customer["status"] != "ACTIVE":
        raise_err("ERR_CUSTOMER_NOT_ACTIVE", "close requires customer ACTIVE")
    if customer["pool_units_outstanding"] != 0:
        raise_err("ERR_POOL_UNITS_OUTSTANDING", "Customer close blocked by outstanding pool units")
    if any(
        o["customer_id"] == cid and o["fulfillment_status"] in OPEN_ORDER_STATES
        for o in db.orders.values()
    ):
        raise_err("ERR_OPEN_ORDERS_EXIST", "Customer close blocked by non-terminal orders")
    customer["status"] = "CLOSED"
    touch(customer)
    return success(serialize(customer))
