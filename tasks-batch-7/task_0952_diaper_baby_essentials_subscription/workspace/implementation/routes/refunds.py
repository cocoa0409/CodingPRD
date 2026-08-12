"""Referrals and refund settlement (PRD 3.10, 3.11)."""

from flask import Blueprint, g

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_referral, get_refund
from envelope import ok, created, paginate
from errors import ApiError
from routes.children import body_fk
from store import db, now, touch

bp = Blueprint("refunds", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]
REFUND_READ_ROLES = ["AccountHolder", "GiftPurchaser", "SupportAgent", "OpsAdmin"]


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------
@api(bp, "POST", "/referrals", ["OpsAdmin"])
def create_referral():
    data = shapes.body()
    body_fk(data, "referrer_account_id", db.accounts, "Account")
    body_fk(data, "referee_account_id", db.accounts, "Account")
    parsed = shapes.validate(data, [
        shapes.field("referrer_account_id", required=True, kind="string"),
        shapes.field("referee_account_id", required=True, kind="string"),
        shapes.field("code", required=True, kind="string"),
    ])
    services.check_referral_policy(parsed["referrer_account_id"],
                                   parsed["referee_account_id"])
    row = services.create_referral(parsed["referrer_account_id"],
                                   parsed["referee_account_id"], parsed["code"])
    return created(serialize.referral(row))


@api(bp, "GET", "/referrals/<id>", READ_ROLES)
def read_referral(id):
    return ok(serialize.referral(get_referral(id)))


@api(bp, "GET", "/referrals", READ_ROLES)
def list_referrals():
    rows = [r for r in db.referrals.values()
            if shapes.match(r, "referrer_account_id",
                            shapes.qs("referrer_account_id"))
            and shapes.match(r, "referee_account_id",
                             shapes.qs("referee_account_id"))
            and shapes.match(r, "vesting_cycle_id", shapes.qs("vesting_cycle_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.referral)


@api(bp, "POST", "/referrals/<id>/expire", ["OpsAdmin"])
def expire_referral(id):
    referral = get_referral(id)
    if referral["status"] != "PENDING":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")
    if now() <= referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_WINDOW_EXPIRED")
    referral["status"] = "EXPIRED"
    touch(referral)
    return ok(serialize.referral(referral))


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
@api(bp, "GET", "/refunds/<id>", REFUND_READ_ROLES)
def read_refund(id):
    return ok(serialize.refund(get_refund(id)))


@api(bp, "GET", "/refunds", REFUND_READ_ROLES)
def list_refunds():
    rows = [r for r in db.refunds.values()
            if shapes.match(r, "account_id", shapes.qs("account_id"))
            and shapes.match(r, "cycle_id", shapes.qs("cycle_id"))
            and shapes.match(r, "gift_order_id", shapes.qs("gift_order_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.refund)


@api(bp, "POST", "/refunds/<id>/approve", ["SupportAgent"])
def approve_refund(id):
    refund = get_refund(id)
    if refund["status"] != "REQUESTED":
        raise ApiError("ERR_REFUND_STATE_INVALID")
    refund["status"] = "APPROVED"
    refund["approved_by_user_id"] = g.user_id
    touch(refund)
    return ok(serialize.refund(refund))


@api(bp, "POST", "/refunds/<id>/deny", ["SupportAgent"])
def deny_refund(id):
    refund = get_refund(id)
    if refund["status"] != "REQUESTED":
        raise ApiError("ERR_REFUND_STATE_INVALID")
    refund["status"] = "DENIED"
    touch(refund)
    return ok(serialize.refund(refund))


@api(bp, "POST", "/refunds/<id>/settle", ["OpsAdmin", "SupportAgent"])
def settle_refund(id):
    refund = get_refund(id)
    cycle = db.cycles.get(refund["cycle_id"]) if refund["cycle_id"] else None
    gift = db.gift_orders.get(refund["gift_order_id"]) \
        if refund["gift_order_id"] else None

    # G5 rung 17 — segregation of duties precedes every lifecycle rung.
    if refund["approved_by_user_id"] is not None and \
            g.user_id == refund["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # G7 rung 25 then rung 34.
    if cycle is not None and \
            cycle["payment_status"] not in ("CHARGED", "PARTIALLY_REFUNDED"):
        raise ApiError("ERR_CYCLE_PAYMENT_STATE_INVALID")
    if refund["status"] != "APPROVED":
        raise ApiError("ERR_REFUND_STATE_INVALID")
    # G9 rung 71.
    amount = int(refund["requested_cents"])
    if cycle is not None:
        if amount > int(cycle["retained_cash_cents"]):
            raise ApiError("ERR_REFUND_EXCEEDS_CHARGE")
    elif gift is not None:
        if amount > int(gift["paid_cents"]):
            raise ApiError("ERR_REFUND_EXCEEDS_CHARGE")

    refund["refunded_cash_cents"] = amount
    refund["status"] = "SETTLED"
    refund["settled_by_user_id"] = g.user_id

    if cycle is not None:
        _settle_pipeline_r(refund, cycle, amount)
    touch(refund)
    return ok(serialize.refund(refund))


def _settle_pipeline_r(refund, cycle, amount):
    charged = int(cycle["charged_cash_cents"])
    retained = int(cycle["retained_cash_cents"]) - amount
    if cycle["payment_status"] == "CHARGED":
        if amount >= charged:
            cycle["payment_status"] = "REFUNDED"
            cycle["retained_cash_cents"] = 0
        else:
            cycle["payment_status"] = "PARTIALLY_REFUNDED"
            cycle["retained_cash_cents"] = max(0, retained)
    else:
        if retained <= 0:
            cycle["payment_status"] = "REFUNDED"
            cycle["retained_cash_cents"] = 0
        else:
            cycle["retained_cash_cents"] = retained
    touch(cycle)

    sub = services.subscription_of_cycle(cycle)
    account_id = sub["account_id"] if sub else None
    wallet = services.wallet_of_account(account_id) if account_id else None
    if wallet is not None:
        # Exactly ONE signed entry restores the redemption and removes the earn.
        delta = int(cycle["loyalty_points_redeemed"]) - int(cycle["points_earned"])
        services.write_ledger_entry(wallet, "CLAWBACK", delta,
                                    cycle_id=cycle["id"])
        touch(wallet)
    refund["points_clawed_back"] = int(cycle["points_earned"])

    restored = 0
    for entry in db.cycle_credit_contributions.get(cycle["id"], []):
        credit = db.credits.get(entry["credit_id"])
        if credit is None:
            continue
        if not credit["refundable"]:
            # GIFT credit is never restored; its cents stay in consumed_cents.
            continue
        services.restore_credit(credit, int(entry["cents"]))
        restored += int(entry["cents"])
    db.cycle_credit_contributions[cycle["id"]] = []
    refund["credits_restored_cents"] = restored

    for referral in list(db.referrals.values()):
        if referral["status"] != "VESTED":
            continue
        if referral["vesting_cycle_id"] != cycle["id"]:
            continue
        referral["status"] = "CLAWED_BACK"
        touch(referral)
        for credit in list(db.credits.values()):
            if credit.get("source_referral_id") != referral["id"]:
                continue
            if credit["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED"):
                services.forfeit_credit(credit, "REVOKED")
        services.recompute_account_estimate(referral["referrer_account_id"])

    if account_id:
        services.recompute_account_estimate(account_id)
