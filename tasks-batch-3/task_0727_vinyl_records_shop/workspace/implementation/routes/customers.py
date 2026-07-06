"""Customer endpoints."""
from flask import Blueprint

import db
from models import base_fields, touch
from middleware import authenticate
from validators import get_body, require_string, require_int, lookup
from response import success
from errors import err, ERR_INVALID_REQUEST
from services import public, recompute_tier

bp = Blueprint("customers", __name__)


@bp.route("/shop/customers", methods=["POST"])
def create_customer():
    # Anonymous allowed (registration). No auth headers required.
    body = get_body()
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    # unique email
    for c in db.db.customers.values():
        if c["email"] == email:
            raise err(ERR_INVALID_REQUEST, "Email already registered")
    cust = base_fields()
    cust.update({
        "email": email,
        "full_name": full_name,
        "store_credit_cents": 0,
        "loyalty_points": 0,
        "loyalty_tier": "STANDARD",
    })
    db.db.customers[cust["id"]] = cust
    return success(public(cust), 201)


@bp.route("/shop/customers/<cid>", methods=["GET"])
def read_customer(cid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    cust = lookup(db.db.customers, cid)
    return success(public(cust), 200)


@bp.route("/shop/customers/<cid>/credit-adjustments", methods=["POST"])
def credit_adjustment(cid):
    authenticate({"Manager"})
    cust = lookup(db.db.customers, cid)
    body = get_body()
    delta = require_int(body, "delta_cents")
    require_string(body, "reason")
    new_balance = cust["store_credit_cents"] + delta
    if new_balance < 0:
        raise err(ERR_INVALID_REQUEST, "store_credit_cents cannot go below zero")
    cust["store_credit_cents"] = new_balance
    touch(cust)
    return success(public(cust), 200)
