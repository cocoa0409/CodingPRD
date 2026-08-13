"""Customer endpoints (PRD 3.1)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_customer, sorted_created, touch
from util import as_bool, as_str, body, pagination_args, reject_unknown, required

bp = Blueprint("customers", __name__)

_FIELDS = {"account_name", "credit_hold", "preferred_currency"}


@bp.post("/label-jobs/customers")
def create_customer():
    auth(["Estimator"])
    data = body()
    reject_unknown(data, _FIELDS)
    account_name = as_str(required(data, "account_name"), "account_name")
    credit_hold = (
        as_bool(data["credit_hold"], "credit_hold") if "credit_hold" in data else False
    )
    currency = (
        as_str(data["preferred_currency"], "preferred_currency")
        if "preferred_currency" in data
        else "USD"
    )
    ts = now_iso()
    customer = {
        "id": new_id(),
        "account_name": account_name,
        "credit_hold": credit_hold,
        "preferred_currency": currency,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["customers"][customer["id"]] = customer
    return ok(customer, 201)


@bp.get("/label-jobs/customers")
def list_customers():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB["customers"].values())
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.get("/label-jobs/customers/<customer_id>")
def get_one_customer(customer_id):
    auth(ALL_ROLES)
    return ok(get_customer(customer_id))


@bp.patch("/label-jobs/customers/<customer_id>")
def update_customer(customer_id):
    auth(["Estimator"])
    customer = get_customer(customer_id)
    data = body()
    reject_unknown(data, _FIELDS)
    if "account_name" in data:
        customer["account_name"] = as_str(data["account_name"], "account_name")
    if "credit_hold" in data:
        customer["credit_hold"] = as_bool(data["credit_hold"], "credit_hold")
    if "preferred_currency" in data:
        customer["preferred_currency"] = as_str(
            data["preferred_currency"], "preferred_currency"
        )
    touch(customer)
    return ok(customer)
