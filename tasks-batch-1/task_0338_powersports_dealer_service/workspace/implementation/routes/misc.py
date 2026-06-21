"""Test-driving clock (PRD 2.10) and customers (PRD 3.1)."""

from flask import Blueprint, request

import errors
from common import get_body, as_str, stamp_new, serialize, touch, paginate
from db import db, parse_iso
from lookups import get_customer
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("misc", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    body = get_body()
    to_iso = as_str(body, "to_iso8601")
    parsed = parse_iso(to_iso)
    if parsed is None:
        errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    db.clock = parsed
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "ServiceAdvisor"})
    body = get_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    phone = as_str(body, "phone")
    # uniqueness: email unique per dealer
    for c in db.customers.values():
        if c["email"] == email:
            errors.err(errors.ERR_DUPLICATE_RESOURCE, "Customer email already exists")
    rec = stamp_new({
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })
    db.customers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "ServiceAdvisor", "FinanceManager", "PartsClerk", "DealerPrincipal"})
    email = request.args.get("email")
    records = [c for c in db.customers.values() if email is None or c["email"] == email]
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer_route(cid):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "ServiceAdvisor", "FinanceManager", "PartsClerk", "DealerPrincipal"})
    rec = get_customer(cid)
    return ok(serialize(rec), 200)
