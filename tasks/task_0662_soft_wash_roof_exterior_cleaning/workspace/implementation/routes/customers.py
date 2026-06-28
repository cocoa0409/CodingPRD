from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_body, require_fields, as_str, as_int,
    get_customer, get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["full_name", "email"])
    full_name = as_str(body["full_name"], "full_name")
    email = as_str(body["email"], "email")
    credit_limit = 0
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        credit_limit = as_int(body["credit_limit_cents"], "credit_limit_cents", minimum=0)
    c = common_create_fields()
    c.update({
        "full_name": full_name,
        "email": email,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[c["id"]] = c
    return success(serialize.customer_view(c), 201)


@bp.get("/customers")
def list_customers():
    _, role = get_identity()
    require_role(role, {"Dispatcher", "BillingAdmin"})
    email = request.args.get("email")
    limit, offset = get_pagination()
    items = [c for c in db.customers.values() if email is None or c["email"] == email]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.customer_view(c) for c in page], limit, offset, total)


@bp.get("/customers/<cid>")
def get_one_customer(cid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "BillingAdmin", "Customer"})
    c = get_customer(cid)
    if role == "Customer" and user_id != c["id"]:
        # Ownership: a customer may only read its own record.
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.customer_view(c), 200)


@bp.post("/customers/<cid>/suspend")
def suspend_customer(cid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    c = get_customer(cid)
    c["status"] = "SUSPENDED"
    touch(c)
    return success(serialize.customer_view(c), 200)
