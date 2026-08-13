"""Customer endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import (
    body_json, req_str, req_int, opt_number, new_record, bump,
    success_object, list_response, get_or_404,
)
import services

bp = Blueprint("customers", __name__)


@bp.post("/fleet/customers")
def create_customer():
    _, role = authenticate()
    authorize(role, ["FleetManager", "SalesRep"])
    body = body_json()
    name = req_str(body, "name")
    credit_limit = req_int(body, "credit_limit_cents")
    if credit_limit < 0:
        raise_err(ERR_INVALID_REQUEST, "credit_limit_cents must be >= 0")
    discount = opt_number(body, "discount_pct", 0)
    if not (0 <= discount < 1):
        raise_err(ERR_INVALID_REQUEST, "discount_pct must satisfy 0 <= discount_pct < 1")
    rec = new_record()
    rec.update({
        "name": name,
        "credit_limit_cents": credit_limit,
        "discount_pct": discount,
        "outstanding_balance_cents": 0,
        "credit_holds_cents": 0,
        "account_status": "ACTIVE",
    })
    store.customers[rec["id"]] = rec
    return success_object(services.serialize_customer(rec), 201)


@bp.get("/fleet/customers/<cid>")
def get_customer(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.customers, cid, "Customer")
    return success_object(services.serialize_customer(c), 200)


@bp.get("/fleet/customers/<cid>/operators")
def list_customer_operators(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.customers, cid, "Customer")
    ops = [o for o in store.operators.values() if o["customer_id"] == c["id"]]
    return list_response(ops, services.serialize_operator)
