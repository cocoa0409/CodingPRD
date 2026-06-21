"""Account endpoints (create, list, get, hold, reinstate)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import stamp_common, touch, serialize, get_account, get_price_tier

bp = Blueprint("accounts", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")
ACCOUNT_TYPES = {"RETAIL", "WHOLESALE"}


@bp.post("/accounts")
def create_account():
    require_role("InventoryManager", "WholesaleRep")
    body = get_body()
    name = c.as_nonempty_string(body, "name", required=True)
    account_type = c.as_enum(body, "account_type", ACCOUNT_TYPES, required=True)
    price_tier_id = c.as_nonempty_string(body, "price_tier_id", required=True)
    credit_limit_cents = c.as_int(body, "credit_limit_cents", required=False, default=0, min_value=0)
    # existence (body)
    get_price_tier(price_tier_id)
    acct = {
        "name": name,
        "account_type": account_type,
        "price_tier_id": price_tier_id,
        "credit_limit_cents": credit_limit_cents,
        "ar_balance_cents": 0,
        "status": "ACTIVE",
    }
    stamp_common(acct)
    db.accounts[acct["id"]] = acct
    return success(serialize(acct), 201)


@bp.get("/accounts")
def list_accounts():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    price_tier_id = request.args.get("price_tier_id")
    account_type = request.args.get("account_type")
    filters = []
    if price_tier_id is not None:
        filters.append(lambda a: a["price_tier_id"] == price_tier_id)
    if account_type is not None:
        filters.append(lambda a: a["account_type"] == account_type)
    page, total = c.paginate(db.accounts.values(), limit, offset, filters)
    return list_success([serialize(a) for a in page], limit, offset, total)


@bp.get("/accounts/<aid>")
def get_one_account(aid):
    require_role(*ALL_ROLES)
    return success(serialize(get_account(aid)))


@bp.post("/accounts/<aid>/hold")
def hold_account(aid):
    require_role("WholesaleRep", "InventoryManager")
    acct = get_account(aid)
    acct["status"] = "ON_HOLD"
    touch(acct)
    return success(serialize(acct))


@bp.post("/accounts/<aid>/reinstate")
def reinstate_account(aid):
    require_role("WholesaleRep", "InventoryManager")
    acct = get_account(aid)
    acct["status"] = "ACTIVE"
    touch(acct)
    return success(serialize(acct))
