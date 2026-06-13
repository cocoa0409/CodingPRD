"""Customer endpoints (PRD §3.1) plus wallet-ledger and recurring-plan reads."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_EMAIL_TAKEN
from middleware import require
from response import ok_array, ok_object
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_str,
    touch,
)
from services.computed import recompute_wallet_credit
from services.lookups import get_customer

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    require(["Customer", "ServiceManager"])
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")

    # email unique across customers (PRD §3.1) -> ERR_EMAIL_TAKEN (409)
    for c in db.customers.values():
        if c["email"] == email:
            raise APIError(ERR_EMAIL_TAKEN, 409, "Email already in use")

    record = init_common({
        "full_name": full_name,
        "email": email,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[record["id"]] = record
    return ok_object(public(record), 201)


@bp.get("/customers/<cid>")
def get_customer_ep(cid):
    require(["Customer", "ServiceManager", "Billing", "Dispatcher"])
    c = get_customer(cid)
    # wallet_credit_cents reflects ledger sum (PRD §2.10) — recompute defensively.
    recompute_wallet_credit(c)
    return ok_object(public(c), 200)


@bp.post("/customers/<cid>/suspend")
def suspend_customer(cid):
    require(["ServiceManager"])
    c = get_customer(cid)
    c["status"] = "SUSPENDED"
    touch(c)
    return ok_object(public(c), 200)


@bp.get("/customers/<cid>/wallet-ledger")
def list_wallet_ledger(cid):
    require(["Customer", "ServiceManager", "Billing"])
    get_customer(cid)
    limit, offset = parse_pagination()
    rows = [e for e in db.wallet_ledger_entries.values() if e["customer_id"] == cid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


@bp.get("/customers/<cid>/recurring-plans")
def list_customer_plans(cid):
    require(["Customer", "ServiceManager"])
    get_customer(cid)
    limit, offset = parse_pagination()
    rows = [p for p in db.recurring_plans.values() if p["customer_id"] == cid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)
