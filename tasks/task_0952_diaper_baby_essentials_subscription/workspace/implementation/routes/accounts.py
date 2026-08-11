"""Households: registration, verification, suspension, closure (PRD 3.1)."""

import uuid

from flask import Blueprint, g

import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_account, require_account_owner
from envelope import ok, created, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("accounts", __name__)


@api(bp, "POST", "/accounts", ["Anonymous", "OpsAdmin"])
def create_account():
    parsed = shapes.validate(shapes.body(), [
        shapes.field("email", required=True, kind="string"),
        shapes.field("full_name", required=True, kind="string"),
        shapes.field("payment_method_on_file", kind="bool", default=False),
        shapes.field("referred_by_code", kind="string", default=None),
    ])
    if "@" not in parsed["email"]:
        raise ApiError("ERR_INVALID_FORMAT", "email must contain an at-sign.")
    for row in db.accounts.values():
        if row["email"] == parsed["email"]:
            raise ApiError("ERR_DUPLICATE_EMAIL")

    account = store.base_row(full=True)
    account.update({
        "email": parsed["email"],
        "full_name": parsed["full_name"],
        "status": "PENDING_VERIFICATION",
        "verification_token": uuid.uuid4().hex,
        "payment_method_on_file": bool(parsed["payment_method_on_file"]),
        "referral_code": uuid.uuid4().hex[:12].upper(),
        "referred_by_code": parsed["referred_by_code"],
        "loyalty_account_id": None,
        "available_credit_cents": 0,
        "next_charge_estimate_cents": 0,
        "suspended_reason": None,
    })
    wallet = store.base_row(full=True)
    wallet.update({
        "account_id": account["id"],
        "points_balance": 0,
        "tier": "BRONZE",
        "trailing_earned_points": 0,
        "tier_evaluated_at": None,
    })
    db.loyalty_accounts[wallet["id"]] = wallet
    account["loyalty_account_id"] = wallet["id"]
    db.accounts[account["id"]] = account
    return created(serialize.account(account))


@api(bp, "GET", "/accounts/<id>", ["AccountHolder", "RegistryOwner",
                                   "GiftPurchaser", "SupportAgent", "OpsAdmin"])
def read_account(id):
    return ok(serialize.account(get_account(id)))


@api(bp, "GET", "/accounts", ["SupportAgent", "OpsAdmin"])
def list_accounts():
    status = shapes.qs("status")
    email = shapes.qs("email")
    loyalty_account_id = shapes.qs("loyalty_account_id")
    rows = [r for r in db.accounts.values()
            if shapes.match(r, "status", status)
            and shapes.match(r, "email", email)
            and shapes.match(r, "loyalty_account_id", loyalty_account_id)]
    return paginate(rows, serialize.account)


@api(bp, "PATCH", "/accounts/<id>", ["AccountHolder", "SupportAgent"])
def update_account(id):
    account = get_account(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("full_name", kind="string"),
        shapes.field("payment_method_on_file", kind="bool"),
    ])
    require_account_owner(account["id"])
    if shapes.supplied(parsed, "full_name"):
        account["full_name"] = parsed["full_name"]
    if shapes.supplied(parsed, "payment_method_on_file"):
        account["payment_method_on_file"] = bool(parsed["payment_method_on_file"])
    touch(account)
    return ok(serialize.account(account))


@api(bp, "POST", "/accounts/<id>/verify", ["Anonymous"])
def verify_account(id):
    account = get_account(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("verification_token", required=True, kind="string"),
    ])
    if account["verification_token"] is None or \
            parsed["verification_token"] != account["verification_token"]:
        raise ApiError("ERR_INVALID_VERIFICATION_TOKEN")

    account["status"] = "ACTIVE"
    account["verification_token"] = None
    touch(account)

    code = account.get("referred_by_code")
    if code:
        referrer = None
        for row in db.accounts.values():
            if row["referral_code"] == code and row["id"] != account["id"]:
                referrer = row
                break
        if referrer is not None:
            try:
                services.check_referral_policy(referrer["id"], account["id"])
            except ApiError:
                # On the verification path a blocked referral is simply NOT
                # created and the verification still succeeds with 200 OK.
                referrer = None
            if referrer is not None:
                services.create_referral(referrer["id"], account["id"], code)
    return ok(serialize.account(account))


@api(bp, "POST", "/accounts/<id>/suspend", ["SupportAgent"])
def suspend_account(id):
    account = get_account(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("reason", required=True, kind="string"),
    ])
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    account["status"] = "SUSPENDED"
    account["suspended_reason"] = parsed["reason"]
    touch(account)
    return ok(serialize.account(account))


@api(bp, "POST", "/accounts/<id>/reinstate", ["SupportAgent"])
def reinstate_account(id):
    account = get_account(id)
    if account["status"] != "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    account["status"] = "ACTIVE"
    account["suspended_reason"] = None
    touch(account)
    return ok(serialize.account(account))


@api(bp, "POST", "/accounts/<id>/close", ["AccountHolder", "SupportAgent"])
def close_account(id):
    account = get_account(id)
    require_account_owner(account["id"])
    if account["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    for sub in services.subscriptions_of_account(account["id"]):
        if sub["lifecycle_state"] in ("ACTIVE", "PAUSED"):
            raise ApiError("ERR_ACCOUNT_HAS_ACTIVE_SUBSCRIPTIONS")

    account["status"] = "CLOSED"
    touch(account)
    for child in db.children.values():
        if child["account_id"] == account["id"] and not child["archived"]:
            child["archived"] = True
            touch(child)
    for credit in services.credits_of_account(account["id"]):
        if credit["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED"):
            services.forfeit_credit(credit, "REVOKED")
    services.recompute_account_estimate(account["id"])
    return ok(serialize.account(account))


@api(bp, "GET", "/accounts/<id>/credit-summary",
     ["AccountHolder", "SupportAgent", "OpsAdmin"])
def credit_summary(id):
    account = get_account(id)
    include_credits = shapes.qs_bool("include_credits", True)
    wallet = services.wallet_of_account(account["id"])
    if wallet is not None:
        services.recompute_wallet_balance(wallet)
    return ok({
        "available_credit_cents": services.available_credit_cents(account["id"]),
        "gift_credit_cents": services.credit_bucket_cents(account["id"], ("GIFT",)),
        "referral_credit_cents": services.credit_bucket_cents(
            account["id"], ("REFERRAL", "GOODWILL", "SHORT_FILL")),
        "points_balance": int(wallet["points_balance"]) if wallet else 0,
        "tier": wallet["tier"] if wallet else "BRONZE",
        "next_charge_estimate_cents": services.next_charge_estimate_cents(
            account["id"], include_credits),
    })
