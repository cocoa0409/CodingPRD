"""Customers, wallet adjustments, loyalty accounts, points ledger entries."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (body, require_fields, require_str, require_int,
                     validate_allergen_array, get_or_404, fk_or_404,
                     paginate, filter_by)
from middleware import get_auth, require_roles, require_owner
from response import success
from serializers import serialize
from services.loyalty import append_ledger_entry, recompute_account

bp = Blueprint("customers", __name__)


# ---------------- Customers ----------------
@bp.post("/customers")
def create_customer():
    # public bootstrap endpoint — no auth required
    data = body()
    require_fields(data, ["email", "full_name", "home_store_id"])
    require_str(data, "email")
    require_str(data, "full_name")
    require_str(data, "home_store_id")
    validate_allergen_array(data, "allergen_blocklist")
    fk_or_404("store", data["home_store_id"])

    # unique email -> ERR_DUPLICATE_EMAIL
    for c in db.customers.values():
        if c["email"] == data["email"]:
            raise err("ERR_DUPLICATE_EMAIL", "Email already in use.")

    customer = db.common_fields()
    customer.update({
        "email": data["email"],
        "full_name": data["full_name"],
        "home_store_id": data["home_store_id"],
        "allergen_blocklist": data.get("allergen_blocklist") or [],
        "wallet_credit_cents": 0,
        "loyalty_account_id": None,
    })

    # create the 1:1 loyalty account
    acct = db.common_fields()
    acct.update({
        "customer_id": customer["id"],
        "points_balance": 0,
        "lifetime_points_earned": 0,
        "tier": "GREEN",
    })
    db.loyalty_accounts[acct["id"]] = acct
    customer["loyalty_account_id"] = acct["id"]

    db.customers[customer["id"]] = customer
    return success(serialize("customer", customer), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    get_auth()
    customer = get_or_404("customer", cid)
    return success(serialize("customer", customer), 200)


@bp.get("/customers")
def list_customers():
    _, role = get_auth()
    require_roles(role, {"StoreManager", "PlatformAdmin"})
    home_store_id = request.args.get("home_store_id")
    items = filter_by(db.customers, home_store_id=home_store_id)
    page, meta = paginate(items)
    return success([serialize("customer", c) for c in page], 200, meta)


@bp.post("/customers/<cid>/wallet/adjustments")
def wallet_adjustment(cid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "StoreManager"})
    customer = get_or_404("customer", cid)
    data = body()
    require_fields(data, ["delta_cents", "reason"])
    require_int(data, "delta_cents")
    require_str(data, "reason")
    customer["wallet_credit_cents"] += data["delta_cents"]
    db.touch(customer)
    return success(serialize("customer", customer), 201)


# ---------------- Loyalty accounts ----------------
@bp.get("/loyalty-accounts")
def list_loyalty_accounts():
    get_auth()
    customer_id = request.args.get("customer_id")
    items = filter_by(db.loyalty_accounts, customer_id=customer_id)
    page, meta = paginate(items)
    return success([serialize("loyalty_account", a) for a in page], 200, meta)


@bp.get("/loyalty-accounts/<aid>")
def get_loyalty_account(aid):
    get_auth()
    acct = get_or_404("loyalty_account", aid)
    return success(serialize("loyalty_account", acct), 200)


# ---------------- Points ledger entries ----------------
@bp.post("/points-ledger-entries")
def create_ledger_entry():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "StoreManager"})
    data = body()
    require_fields(data, ["loyalty_account_id", "delta_points", "reason"])
    require_str(data, "loyalty_account_id")
    require_int(data, "delta_points")
    require_str(data, "reason")
    # operator adjustment: reason must be ADJUSTMENT (§3.3, endpoint table)
    if data["reason"] != "ADJUSTMENT":
        raise err("ERR_INVALID_REQUEST", "reason must be ADJUSTMENT.")
    fk_or_404("loyalty_account", data["loyalty_account_id"])
    entry = append_ledger_entry(
        data["loyalty_account_id"], data["delta_points"], "ADJUSTMENT", order_id=None
    )
    return success(serialize("points_ledger_entry", entry), 201)


@bp.get("/points-ledger-entries/<eid>")
def get_ledger_entry(eid):
    get_auth()
    entry = get_or_404("points_ledger_entry", eid)
    return success(serialize("points_ledger_entry", entry), 200)


@bp.get("/points-ledger-entries")
def list_ledger_entries():
    get_auth()
    loyalty_account_id = request.args.get("loyalty_account_id")
    order_id = request.args.get("order_id")
    items = filter_by(db.points_ledger_entries,
                      loyalty_account_id=loyalty_account_id, order_id=order_id)
    page, meta = paginate(items)
    return success([serialize("points_ledger_entry", e) for e in page], 200, meta)
