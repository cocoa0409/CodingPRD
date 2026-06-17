"""Customer routes (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_object
from services.validation import lookup_path_or_404, require_fields, require_string

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    require_auth(["ServiceAdvisor"])()
    body = get_json_body()
    require_fields(body, ["email", "full_name", "phone"])
    email = require_string(body["email"], "email")
    full_name = require_string(body["full_name"], "full_name")
    phone = require_string(body["phone"], "phone")

    with db.mutation_lock:
        for c in db.customers.values():
            if c["email"] == email:
                raise APIError(ERR_INVALID_REQUEST, 422, "email already in use")
        customer = {
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "store_credit_cents": 0,
        }
        db.stamp_common(customer)
        db.customers[customer["id"]] = customer
        return ok_object(customer, 201)


@bp.get("/customers/<cid>")
def get_customer(cid: str):
    require_auth(["ServiceAdvisor", "Customer"])()
    customer = lookup_path_or_404(db.customers, cid, "Customer")
    return ok_object(customer, 200)
