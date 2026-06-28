"""Customer endpoints (PRD 3.1)."""

from flask import Blueprint

from common import get_json_body, require_fields, require_string, stamp_new
from db import db
from errors import err
from lookups import get_customer
from middleware import get_auth, require_role
from response import success
from services.serialize import ser_customer

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_auth()
    require_role(role, {"OperationsAdmin"})
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")

    # Email uniqueness, case-insensitive (priority 16 -> ERR_DUPLICATE_EMAIL).
    lowered = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lowered:
            raise err("ERR_DUPLICATE_EMAIL", "Customer email already exists.")

    record = stamp_new(
        {
            "full_name": full_name,
            "email": email,
            "wallet_credit_cents": 0,
        }
    )
    db.customers[record["id"]] = record
    return success(ser_customer(record), status=201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    _, role = get_auth()
    require_role(role, {"OperationsAdmin", "Customer"})
    c = get_customer(cid)
    return success(ser_customer(c), status=200)
