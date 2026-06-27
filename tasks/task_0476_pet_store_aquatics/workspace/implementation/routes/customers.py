"""Customer endpoints (PRD §3.13)."""
from flask import Blueprint, request

import db
from db import stamp_create
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str,
)
from services.serialize import customer_out

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = require_auth()
    require_role(role, ["StoreClerk", "InventoryManager"])
    body = get_body()
    email = as_str(require_present(body, "email"), "email")
    full_name = as_str(require_present(body, "full_name"), "full_name")
    home_store_id = as_str(require_present(body, "home_store_id"), "home_store_id")
    lookup("stores", home_store_id)

    # Uniqueness: email globally unique (PRD §2.7).
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_RESOURCE", "Customer email must be globally unique.")

    record = {
        "email": email,
        "full_name": full_name,
        "home_store_id": home_store_id,
        "loyalty_points": 0,
        "lifetime_spend_cents": 0,
    }
    stamp_create(record)
    db.customers[record["id"]] = record
    return object_response(customer_out(record), 201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = require_auth()
    require_role(role, ["InventoryManager", "StoreClerk", "ClinicVet"])
    limit, offset = parse_pagination()
    records = list(db.customers.values())
    home_store_id = request.args.get("home_store_id")
    if home_store_id is not None:
        records = [r for r in records if r["home_store_id"] == home_store_id]
    page, total = paginate(records, limit, offset)
    return array_response([customer_out(r) for r in page], limit, offset, total)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    _, role = require_auth()
    require_role(role, ["InventoryManager", "StoreClerk", "ClinicVet", "Customer"])
    record = lookup("customers", customer_id)
    return object_response(customer_out(record))
