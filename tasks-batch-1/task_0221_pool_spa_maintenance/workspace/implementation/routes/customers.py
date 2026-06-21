"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.common import (
    new_record,
    optional_enum,
    require_json_object,
    require_str,
    serialize,
    touch,
)

bp = Blueprint("customers", __name__)

BILLING_TERMS = {"PER_VISIT", "MONTHLY_ACCRUAL"}


@bp.post("/customers")
@require_roles("AccountManager")
def create_customer():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        full_name = require_str(body, "full_name")
        email = require_str(body, "email")
        billing_terms = optional_enum(body, "billing_terms", BILLING_TERMS, "PER_VISIT")
        # email unique across customers (PRD §3.1).
        for c in db.customers.values():
            if c["email"] == email:
                raise err("ERR_INVALID_REQUEST", "Customer email already exists")
        rec = new_record(
            {
                "full_name": full_name,
                "email": email,
                "billing_terms": billing_terms,
                "account_status": "ACTIVE",
            }
        )
        db.customers[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/customers/<customer_id>")
@require_roles("AccountManager", "Customer")
def get_customer(customer_id):
    with db.lock:
        c = db.customers.get(customer_id)
        if not c:
            raise err("ERR_NOT_FOUND", "Customer not found")
        return success(serialize(c), 200)


@bp.post("/customers/<customer_id>/suspend")
@require_roles("AccountManager")
def suspend_customer(customer_id):
    with db.lock:
        c = db.customers.get(customer_id)
        if not c:
            raise err("ERR_NOT_FOUND", "Customer not found")
        c["account_status"] = "SUSPENDED"
        touch(c)
        return success(serialize(c), 200)
