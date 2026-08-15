"""Customer master data endpoints."""
from flask import Blueprint

from db import store, new_id, touch, new_common
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services.audit import audit

bp = Blueprint("customers", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "InventoryClerk", "CustomerRep"]


@bp.post("/fab/customers")
def create_customer():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({
        "company_name": ("string", True, None),
        "email": ("string", True, None),
        "credit_limit_cents": ("integer", True, None),
    }, allow_empty=False)
    customer = {
        "id": new_id(),
        "company_name": body["company_name"],
        "email": body["email"],
        "credit_limit_cents": body["credit_limit_cents"],
        "scrap_credit_balance_cents": 0,
        "status": "ACTIVE",
    }
    new_common(customer)
    store.customers[customer["id"]] = customer
    audit("Customer", customer["id"], "CUSTOMER_CREATED", role, uid,
          {"after": {"status": "ACTIVE"}})
    return created(customer)


@bp.get("/fab/customers")
def list_customers():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.customers.values())
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/customers/<customer_id>")
def get_customer(customer_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.customers, customer_id))


@bp.post("/fab/customers/<customer_id>/suspend")
def suspend_customer(customer_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    c = require_path_entity(store.customers, customer_id)
    prev = c["status"]
    c["status"] = "SUSPENDED"
    touch(c)
    audit("Customer", c["id"], "CUSTOMER_SUSPENDED", role, uid,
          {"before": {"status": prev}, "after": {"status": "SUSPENDED"}})
    return ok(c)
