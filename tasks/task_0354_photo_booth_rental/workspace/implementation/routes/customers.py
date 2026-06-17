"""Customer self-registration and read (PRD §3.2)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success
import helpers
from services.serialize import plain_out

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    # PRD §2.1: anonymous, no auth headers required.
    body = helpers.get_json()
    email = helpers.require_string(body, "email")
    full_name = helpers.require_string(body, "full_name")
    home_zip = helpers.optional_string(body, "home_zip", None)
    # Uniqueness (priority 21).
    for c in db.customers.values():
        if c["email"] == email:
            raise err(errors.ERR_DUPLICATE_KEY, "Customer email already in use.")

    rec = db.common_create()
    rec.update({"email": email, "full_name": full_name, "home_zip": home_zip})
    db.customers[rec["id"]] = rec
    return success(plain_out(rec), 201)


@bp.route("/customers/<cust_id>", methods=["GET"])
def get_customer(cust_id):
    _, role = authenticate()
    require_role(role, {"Customer", "OperationsManager", "PlatformAdmin"})
    rec = db.customers.get(cust_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Customer not found.")
    return success(plain_out(rec), 200)
