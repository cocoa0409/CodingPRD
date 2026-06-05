"""Customer routes (PRD §3.1).

POST /customers is the only anonymous endpoint — no auth headers required.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object
from services.validation import (
    require_fields,
    require_string,
    require_email,
    lookup_or_404,
)
from services.ownership import assert_customer_owns_customer


bp = Blueprint("customers", __name__)


@bp.post("/customers")
def register_customer():
    # Anonymous endpoint: no auth headers required (PRD §2.1).
    body = get_json_body()
    require_fields(body, ["email", "full_name", "home_address"])
    email = require_email(body["email"], "email")
    full_name = body["full_name"]
    require_string(full_name, "full_name")
    home_address = body["home_address"]
    require_string(home_address, "home_address")

    # Email is unique across customers.
    for c in db.customers.values():
        if c["email"] == email:
            raise APIError(ERR_INVALID_REQUEST, 400, f"email already exists: {email}")

    customer = {
        "email": email,
        "full_name": full_name,
        "home_address": home_address,
    }
    db.stamp_common(customer)
    db.customers[customer["id"]] = customer
    return ok_object(customer, 201)


@bp.get("/customers/<cid>")
def get_customer(cid: str):
    require_auth(["PlatformAdmin", "Customer"])()
    customer = lookup_or_404(db.customers, cid, "Customer")
    assert_customer_owns_customer(customer, current_role(), current_user_id())
    return ok_object(customer, 200)
