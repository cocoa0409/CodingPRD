"""Customer registration and retrieval."""
from flask import Blueprint

import db
from auth import check_ownership, require_roles
from db import common_fields
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from serialize import pub_customer
from util import as_int, as_str, body, ok, require

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    require_roles("SalesRep")
    payload = body()
    full_name = as_str(require(payload, "full_name"), "full_name")
    email = as_str(require(payload, "email"), "email")
    phone = as_str(require(payload, "phone"), "phone")
    freight_zone = as_int(require(payload, "freight_zone"), "freight_zone", minimum=1, maximum=3)
    address = as_str(require(payload, "address"), "address")
    for c in db.store.customers.values():
        if c["email"] == email:
            raise err(ERR_INVALID_REQUEST, f"email '{email}' is already registered")
    customer = common_fields()
    customer.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "freight_zone": freight_zone,
        "address": address,
    })
    db.store.customers[customer["id"]] = customer
    return ok(pub_customer(customer), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    customer = db.store.customers.get(cid)
    if customer is None:
        raise err(ERR_NOT_FOUND, f"customer {cid} not found")
    check_ownership(user_id, role, customer["id"])
    return ok(pub_customer(customer), 200)
