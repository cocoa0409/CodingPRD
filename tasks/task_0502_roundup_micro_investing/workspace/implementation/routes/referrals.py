"""Referral routes (PRD §3.11): issue/redeem/release/qualify/expire/revoke."""

import datetime

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, parse_iso8601, require_auth, require_owner
from models import create_cash_transaction, new_entity, serialize, touch
from response import success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_int,
    require_str,
)

bp = Blueprint("referrals", __name__)

_WINDOW = datetime.timedelta(days=30)


def _created_dt(referral):
    return parse_iso8601(referral["created_at"])


@bp.route("/referrals", methods=["POST"])
def issue_referral():
    role, user_id = require_auth({"Investor"})
    body = get_json()
    referrer_account_id = require_str(body, "referrer_account_id")
    code = require_str(body, "code")
    bonus_cents = require_int(body, "bonus_cents", minimum=1)

    account = fetch_or_404(store.accounts, referrer_account_id)
    require_owner(role, user_id, account["id"])

    # Unique code (PRD §3.11 -> ERR_DUPLICATE_TIER).
    for r in store.referrals.values():
        if r["code"] == code:
            raise err("ERR_DUPLICATE_TIER", "Referral code already exists.")

    referral = new_entity(
        {
            "referrer_account_id": referrer_account_id,
            "referred_account_id": None,
            "code": code,
            "bonus_cents": bonus_cents,
            "status": "ISSUED",
        }
    )
    store.referrals[referral["id"]] = referral
    return success(serialize(referral), status=201)


@bp.route("/referrals/<entity_id>", methods=["GET"])
def get_referral(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    referral = fetch_or_404(store.referrals, entity_id)
    require_owner(role, user_id, referral["referrer_account_id"])
    return success(serialize(referral))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    items = list(store.referrals.values())
    referrer_account_id = request.args.get("referrer_account_id")
    referred_account_id = request.args.get("referred_account_id")
    status = request.args.get("status")
    if referrer_account_id is not None:
        items = [r for r in items if r["referrer_account_id"] == referrer_account_id]
    if referred_account_id is not None:
        items = [r for r in items if r["referred_account_id"] == referred_account_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if role == "Investor":
        items = [r for r in items if r["referrer_account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/referrals/<entity_id>/redeem", methods=["POST"])
def redeem_referral(entity_id):
    role, user_id = require_auth({"Investor"})
    referral = fetch_or_404(store.referrals, entity_id)
    body = get_json()
    referred_account_id = require_str(body, "referred_account_id")

    # The redeeming account must exist and be owned by the caller.
    redeemer = fetch_or_404(store.accounts, referred_account_id)
    require_owner(role, user_id, redeemer["id"])

    # State (priority 7): referral ISSUED.
    if referral["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED referral can be redeemed.")

    # Self-referral (priority 14).
    if referred_account_id == referral["referrer_account_id"]:
        raise err("ERR_SELF_REFERRAL", "Referrer cannot redeem their own referral.")

    # Window (priority 13): clock strictly before created_at + 30 days.
    if not (store.now() < _created_dt(referral) + _WINDOW):
        raise err("ERR_REFERRAL_WINDOW", "Referral redemption window has elapsed.")

    referral["status"] = "REDEEMED"
    referral["referred_account_id"] = referred_account_id
    touch(referral)
    return success(serialize(referral))


@bp.route("/referrals/<entity_id>/release-redemption", methods=["POST"])
def release_redemption(entity_id):
    role, user_id = require_auth({"Investor"})
    referral = fetch_or_404(store.referrals, entity_id)
    # Ownership: the redeemer (referred account) releases their own redemption.
    require_owner(role, user_id, referral["referred_account_id"])
    if referral["status"] != "REDEEMED":
        raise err("ERR_INVALID_STATE", "Only a REDEEMED referral can be released.")
    referral["status"] = "ISSUED"
    referral["referred_account_id"] = None
    touch(referral)
    return success(serialize(referral))


@bp.route("/referrals/<entity_id>/qualify", methods=["POST"])
def qualify_referral(entity_id):
    require_auth({"PlatformAdmin"})
    referral = fetch_or_404(store.referrals, entity_id)
    if referral["status"] != "REDEEMED":
        raise err("ERR_INVALID_STATE", "Only a REDEEMED referral can be qualified.")
    referred = store.accounts[referral["referred_account_id"]]
    if referred["lifetime_invested_cents"] < 500:
        raise err("ERR_INVALID_STATE", "Referred account has not invested enough to qualify.")

    referrer = store.accounts[referral["referrer_account_id"]]
    bonus = referral["bonus_cents"]

    referral["status"] = "QUALIFIED"
    touch(referral)

    # Pay both sides; bump derived referral_credits and write two ledger rows.
    referrer["cash_balance_cents"] = referrer["cash_balance_cents"] + bonus
    referred["cash_balance_cents"] = referred["cash_balance_cents"] + bonus
    referrer["referral_credits_cents"] = referrer["referral_credits_cents"] + bonus
    referred["referral_credits_cents"] = referred["referral_credits_cents"] + bonus
    create_cash_transaction(referrer["id"], "REFERRAL_BONUS", bonus, "CONFIRMED")
    create_cash_transaction(referred["id"], "REFERRAL_BONUS", bonus, "CONFIRMED")
    return success(serialize(referral))


@bp.route("/referrals/<entity_id>/expire", methods=["POST"])
def expire_referral(entity_id):
    require_auth({"PlatformAdmin"})
    referral = fetch_or_404(store.referrals, entity_id)
    if referral["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED referral can be expired.")
    # Window (priority 13): clock at/after created_at + 30 days.
    if not (store.now() >= _created_dt(referral) + _WINDOW):
        raise err("ERR_REFERRAL_WINDOW", "Referral window has not yet elapsed.")
    referral["status"] = "EXPIRED"
    touch(referral)
    return success(serialize(referral))


@bp.route("/referrals/<entity_id>/revoke", methods=["POST"])
def revoke_referral(entity_id):
    role, user_id = require_auth({"Investor"})
    referral = fetch_or_404(store.referrals, entity_id)
    require_owner(role, user_id, referral["referrer_account_id"])
    if referral["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED referral can be revoked.")
    referral["status"] = "REVOKED"
    touch(referral)
    return success(serialize(referral))
