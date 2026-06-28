"""Customer + credit-wallet endpoints (PRD §3.1)."""
from flask import Blueprint, g

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response

bp = Blueprint("customers", __name__)


@bp.post("/studio-ops/customers")
def create_customer():
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    email = helpers.as_str(body, "email")
    full_name = helpers.as_str(body, "full_name")
    birthdate = helpers.parse_datetime(body, "birthdate")
    # Uniqueness: case-insensitive email (ERR_DUPLICATE_RESOURCE).
    lowered = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lowered:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Email already registered")
    rec = models.make_customer(email, full_name, birthdate)
    db.customers[rec["id"]] = rec
    return object_response(models.serialize_customer(rec), 201)


@bp.get("/studio-ops/customers/<cid>")
def get_customer(cid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.customers.get(cid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Customer not found")
    # A Customer may only read their own profile.
    if middleware.is_customer() and g.user_id != cid:
        raise err(errors.ERR_FORBIDDEN, "Customers may only read their own profile")
    return object_response(models.serialize_customer(rec), 200)


@bp.post("/studio-ops/customers/<cid>/credit-adjustments")
def adjust_credit(cid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    rec = db.customers.get(cid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Customer not found")
    body = helpers.get_json_body()
    # amount_cents may be negative (debit) — no min bound, but must be an int.
    amount = helpers.as_int(body, "amount_cents")
    helpers.as_str(body, "reason")
    new_balance = rec["credit_balance_cents"] + amount
    if new_balance < 0:
        raise err(errors.ERR_CREDIT_INSUFFICIENT,
                  "Adjustment would drive credit balance below 0")
    rec["credit_balance_cents"] = new_balance
    models.touch(rec)
    return object_response(models.serialize_customer(rec), 200)
