"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint, request

from store import STORE
from helpers import (endpoint, get_body, validate_payload, ok, created, ok_list,
                     paginate, filter_eq, sort_created, not_found, stamp_new)
from domain import ser_customer

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@endpoint(roles=["ShopAdmin"])
def create_customer(uid, role):
    data = validate_payload(get_body(), [
        ("company_name", "str", True),
        ("contact_email", "str", True),
        ("credit_limit_cents", "int", False, {"min": 0}),
    ])
    cust = stamp_new({
        "company_name": data["company_name"],
        "contact_email": data["contact_email"],
        "credit_limit_cents": data.get("credit_limit_cents", 0),
        "status": "ACTIVE",
    })
    STORE.customers[cust["id"]] = cust
    return created(ser_customer(cust))


@bp.route("/customers", methods=["GET"])
@endpoint(roles=None)
def list_customers(uid, role):
    items = sort_created(list(STORE.customers.values()))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_customer(c) for c in page], meta)


@bp.route("/customers/<customerId>", methods=["GET"])
@endpoint(roles=None)
def get_customer(uid, role, customerId):
    cust = STORE.customers.get(customerId)
    if cust is None:
        not_found("CUSTOMER")
    return ok(ser_customer(cust))
