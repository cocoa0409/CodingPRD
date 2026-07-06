from __future__ import annotations
from flask import Blueprint

from db import db, stamp_common
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import require_roles
from response import created, ok
from routes._helpers import get_body, require_field, fetch, clean

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@require_roles("StoreClerk")
def create_customer():
    body = get_body()
    email = require_field(body, "email")
    full_name = require_field(body, "full_name")
    if not isinstance(email, str) or not email:
        raise_error(ERR_INVALID_REQUEST, "email must be non-empty string")
    if not isinstance(full_name, str) or not full_name:
        raise_error(ERR_INVALID_REQUEST, "full_name must be non-empty string")
    for existing in db.customers.values():
        if existing["email"] == email:
            raise_error(ERR_INVALID_REQUEST, f"email '{email}' already exists")
    cust = {"email": email, "full_name": full_name, "store_credit_cents": 0}
    stamp_common(cust)
    db.customers[cust["id"]] = cust
    return created(clean(cust))


@bp.route("/customers/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_customer(id):
    return ok(clean(fetch(db.customers, id)))
