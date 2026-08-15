"""Customers (PRD 3.1)."""
from flask import Blueprint, request

from authz import ANALYST, ANY_ROLE, require_roles
from db import store
from errors import customer_not_found, invalid_request
from response import success
from serialize import ser_customer
from store_ops import json_body, new_id, req_str, stamp_new

bp = Blueprint("customers", __name__)


@bp.route("/margin/customers", methods=["POST"])
def create_customer():
    data = json_body()
    legal_name = req_str(data, "legal_name")
    email = req_str(data, "email")
    require_roles([ANALYST])
    # Email is unique across customers (PRD 3.1); the error catalogue has no
    # dedicated code, so a duplicate is a malformed request.
    if any(c["email"] == email for c in store.customers.values()):
        raise invalid_request("email must be unique across customers")
    customer = {"id": new_id(), "legal_name": legal_name, "email": email}
    stamp_new(customer)
    store.customers[customer["id"]] = customer
    return success(ser_customer(customer), status=201)


@bp.route("/margin/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_roles(ANY_ROLE)
    customer = store.customers.get(cid)
    if customer is None:
        raise customer_not_found()
    return success(ser_customer(customer))
