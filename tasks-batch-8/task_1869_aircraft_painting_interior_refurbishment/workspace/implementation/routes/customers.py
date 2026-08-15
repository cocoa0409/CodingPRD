"""Customer endpoints."""
from flask import Blueprint, request

from db import STORE
from domain import new_entity, bump, get_or_404, by_created, serialize_customer
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("customers", __name__)

CREDIT_STATUSES = ("GOOD_STANDING", "CREDIT_HOLD")


@bp.post("/customers")
def create_customer():
    auth("CenterAdmin")
    data = get_body(required=True)
    name = field(data, "name", "str")
    contact_email = field(data, "contact_email", "str")
    cust = new_entity()
    cust.update({"name": name, "contact_email": contact_email,
                 "credit_status": "GOOD_STANDING"})
    STORE.customers[cust["id"]] = cust
    return success(serialize_customer(cust), status=201)


@bp.get("/customers")
def list_customers():
    auth()  # any declared role
    items = by_created(list(STORE.customers.values()))
    credit = request.args.get("credit_status")
    if credit is not None:
        items = [c for c in items if c["credit_status"] == credit]
    return paginate(items, serialize_customer)


@bp.post("/customers/<cid>/credit-status")
def set_credit_status(cid):
    auth("CenterAdmin")
    data = get_body(required=True)
    status = field(data, "credit_status", "str", enum=CREDIT_STATUSES)
    cust = get_or_404(STORE.customers, cid, "Customer")
    cust["credit_status"] = status
    bump(cust)
    return success(serialize_customer(cust))
