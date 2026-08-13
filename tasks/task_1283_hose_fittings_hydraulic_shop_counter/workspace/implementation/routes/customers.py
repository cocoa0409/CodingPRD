"""Customers: registration, flag updates, computed compliance read
(PRD §3.1)."""

from flask import Blueprint

from db import store, new_entity, touch
from middleware import (
    require_roles, body, get_or_404, check_customer_scope,
    get_str, get_bool, get_int, get_num, present,
)
from response import success
from services import serialize_customer

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
def create_customer():
    require_roles("ShopManager")
    data = body()
    customer = new_entity()
    customer.update({
        "name": get_str(data, "name"),
        "credit_hold": get_bool(data, "credit_hold", required=False, default=False),
        "program_enrolled": get_bool(data, "program_enrolled", required=False, default=False),
        "program_discount_pct": get_num(data, "program_discount_pct", required=False, default=0),
        "inspection_interval_days": get_int(data, "inspection_interval_days",
                                            required=False, default=365, min_val=1),
    })
    store.customers[customer["id"]] = customer
    return success(serialize_customer(customer), status=201)


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    uid, role = require_roles("ShopManager", "CounterSales", "Customer")
    # ownership (priority 2) before existence for the entity-backed role
    check_customer_scope(role, uid, cid)
    customer = get_or_404(store.customers, cid, "customer")
    return success(serialize_customer(customer), status=200)


@bp.patch("/api/customers/<cid>")
def update_customer(cid):
    require_roles("ShopManager")
    customer = get_or_404(store.customers, cid, "customer")
    data = body()
    if present(data, "name"):
        customer["name"] = get_str(data, "name")
    if present(data, "credit_hold"):
        customer["credit_hold"] = get_bool(data, "credit_hold")
    if present(data, "program_enrolled"):
        customer["program_enrolled"] = get_bool(data, "program_enrolled")
    if present(data, "program_discount_pct"):
        customer["program_discount_pct"] = get_num(data, "program_discount_pct")
    interval_changed = False
    if present(data, "inspection_interval_days"):
        new_interval = get_int(data, "inspection_interval_days", min_val=1)
        interval_changed = new_interval != customer["inspection_interval_days"]
        customer["inspection_interval_days"] = new_interval
    touch(customer)
    # interval change recomputes next_due_date on each of the customer's
    # assets — a cascade touch per asset (PRD §3.1, §2.4)
    if interval_changed:
        for asset in store.assets.values():
            if asset["customer_id"] == cid:
                touch(asset)
    return success(serialize_customer(customer), status=200)
