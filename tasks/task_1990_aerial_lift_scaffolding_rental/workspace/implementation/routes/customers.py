"""Customer accounts: create, read, reinstate."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, forbid
from response import ok, created
from services import calc, domain
from validation import validate_body

bp = Blueprint("customers", __name__)


@bp.post("/customer-accounts")
def create_customer():
    uid, role = get_context()
    require_roles(["BranchManager"])
    body = validate_body({
        "company_name": ("string", True),
        "contact_email": ("string", True),
        "credit_limit_cents": ("integer", True, {"min": 0}),
    })
    customer = db.new_common({
        "id": db.new_id(),
        "company_name": body["company_name"],
        "contact_email": body["contact_email"],
        "credit_limit_cents": body["credit_limit_cents"],
        "status": "ACTIVE",
    })
    store.customers[customer["id"]] = customer
    return created(domain.view_customer(customer))


@bp.get("/customer-accounts/<cid>")
def get_customer(cid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    if role == "Customer" and cid != uid:
        forbid("A Customer may read only its own customer record")
    customer = store.customers.get(cid)
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer account not found")
    return ok(domain.view_customer(customer))


@bp.post("/customer-accounts/<cid>/reinstate")
def reinstate_customer(cid):
    uid, role = get_context()
    require_roles(["BranchManager"])
    customer = store.customers.get(cid)
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer account not found")
    if customer["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Customer is not SUSPENDED")
    balance = calc.customer_balance_cents(cid)
    if balance > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Outstanding balance exceeds the credit limit")
    customer["status"] = "ACTIVE"
    db.touch(customer)
    return ok(domain.view_customer(customer))
