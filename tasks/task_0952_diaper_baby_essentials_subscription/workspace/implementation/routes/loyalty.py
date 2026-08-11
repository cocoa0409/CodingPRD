"""Loyalty wallets, redemptions, expiry sweeps and tier re-evaluation."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_loyalty, lookup, require_account_owner
from envelope import ok, created, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("loyalty", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]


@api(bp, "GET", "/loyalty-accounts/<id>", READ_ROLES)
def read_wallet(id):
    return ok(serialize.loyalty_account(get_loyalty(id)))


@api(bp, "GET", "/loyalty-accounts", READ_ROLES)
def list_wallets():
    rows = [r for r in db.loyalty_accounts.values()
            if shapes.match(r, "account_id", shapes.qs("account_id"))
            and shapes.match(r, "tier", shapes.qs("tier"))]
    return paginate(rows, serialize.loyalty_account)


@api(bp, "POST", "/loyalty-accounts/<id>/redemptions", ["AccountHolder"])
def redeem(id):
    wallet = get_loyalty(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("points", required=True, kind="int"),
    ])
    require_account_owner(wallet["account_id"])
    services.recompute_wallet_balance(wallet)
    points = parsed["points"]
    if points < C.POINT_REDEMPTION_FLOOR_POINTS:
        raise ApiError("ERR_REDEMPTION_BELOW_FLOOR")
    if points > int(wallet["points_balance"]):
        raise ApiError("ERR_INSUFFICIENT_POINTS")

    entry = services.write_ledger_entry(wallet, "REDEEM", -points, cycle_id=None)
    touch(wallet)
    services.issue_credit(
        wallet["account_id"], "GOODWILL", points * C.POINT_VALUE_CENTS, True,
        store.plus_days(now(), C.CREDIT_EXPIRY_DAYS))
    services.recompute_account_estimate(wallet["account_id"])
    return created(serialize.points_ledger_entry(entry))


@api(bp, "POST", "/loyalty-accounts/<id>/expire-points", ["OpsAdmin"])
def expire_points(id):
    wallet = get_loyalty(id)
    services.points_expiry_sweep(wallet)
    touch(wallet)
    return ok(serialize.loyalty_account(wallet))


@api(bp, "POST", "/loyalty-accounts/<id>/reevaluate-tier", ["OpsAdmin"])
def reevaluate_tier(id):
    wallet = get_loyalty(id)
    services.recompute_wallet_balance(wallet)
    # The ONLY path that can move a tier downward.
    tier = services.evaluate_tier(wallet, upgrade_only=False)
    touch(wallet)
    eligible = tier in ("SILVER", "GOLD")
    for sub in services.subscriptions_of_account(wallet["account_id"]):
        if sub["lifecycle_state"] == "CANCELLED":
            continue
        if bool(sub["free_shipping_eligible"]) != eligible:
            sub["free_shipping_eligible"] = eligible
            touch(sub)
    return ok(serialize.loyalty_account(wallet))


@api(bp, "GET", "/points-ledger-entries/<id>", READ_ROLES)
def read_entry(id):
    return ok(serialize.points_ledger_entry(
        lookup(db.points_ledger_entries, id, "PointsLedgerEntry")))


@api(bp, "GET", "/points-ledger-entries", READ_ROLES)
def list_entries():
    rows = [r for r in db.points_ledger_entries.values()
            if shapes.match(r, "loyalty_account_id",
                            shapes.qs("loyalty_account_id"))
            and shapes.match(r, "cycle_id", shapes.qs("cycle_id"))
            and shapes.match(r, "entry_type", shapes.qs("entry_type"))]
    return paginate(rows, serialize.points_ledger_entry)
