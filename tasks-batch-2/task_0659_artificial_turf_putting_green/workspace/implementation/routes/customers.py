"""Customers (PRD 3.1). Created by SalesRep or OpsAdmin; email unique
case-insensitively."""

from flask import Blueprint

from common import get_json_body, public, require_fields, require_string, stamp_new
from db import db
from errors import err
from lookups import get_customer_or_404
from middleware import get_auth, require_role
from response import success

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")

    # Email uniqueness, case-insensitive (priority 7).
    lowered = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lowered:
            raise err("ERR_DUPLICATE_RESOURCE", "Email already exists.")

    rec = {"full_name": full_name, "email": email}
    stamp_new(rec)
    db.customers[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    rec = get_customer_or_404(customer_id)
    return success(public(rec), status=200)
