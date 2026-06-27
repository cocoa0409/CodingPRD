"""FoundMoneyReward routes (PRD §3.10)."""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, parse_iso8601, require_auth, require_owner
from models import create_cash_transaction, new_entity, serialize, touch
from response import format_ts, success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_int,
    require_str,
)
from services.calc import add_days, found_money_rebate

bp = Blueprint("rewards", __name__)


@bp.route("/found-money-rewards", methods=["POST"])
def earn_reward():
    role, user_id = require_auth({"Investor"})
    body = get_json()
    account_id = require_str(body, "account_id")
    offer_id = require_str(body, "offer_id")
    qualifying_spend_cents = require_int(body, "qualifying_spend_cents", minimum=1)

    account = fetch_or_404(store.accounts, account_id)
    offer = fetch_or_404(store.found_money_offers, offer_id)
    require_owner(role, user_id, account["id"])

    # Min-spend gate (PRD §3.10).
    if qualifying_spend_cents < offer["min_spend_cents"]:
        raise err("ERR_MIN_SPEND_NOT_MET", "Qualifying spend is below the offer minimum.")

    rebate = found_money_rebate(offer, qualifying_spend_cents)
    eligible_at = add_days(store.now(), offer["hold_days"])

    reward = new_entity(
        {
            "account_id": account_id,
            "offer_id": offer_id,
            "qualifying_spend_cents": qualifying_spend_cents,
            "rebate_amount_cents": rebate,
            "eligible_at": format_ts(eligible_at),
            "status": "PENDING",
        }
    )
    store.found_money_rewards[reward["id"]] = reward
    return success(serialize(reward), status=201)


@bp.route("/found-money-rewards/<entity_id>", methods=["GET"])
def get_reward(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    reward = fetch_or_404(store.found_money_rewards, entity_id)
    require_owner(role, user_id, reward["account_id"])
    return success(serialize(reward))


@bp.route("/found-money-rewards", methods=["GET"])
def list_rewards():
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    items = list(store.found_money_rewards.values())
    account_id = request.args.get("account_id")
    offer_id = request.args.get("offer_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if offer_id is not None:
        items = [r for r in items if r["offer_id"] == offer_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if role == "Investor":
        items = [r for r in items if r["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/found-money-rewards/<entity_id>/confirm", methods=["POST"])
def confirm_reward(entity_id):
    require_auth({"PlatformAdmin"})
    reward = fetch_or_404(store.found_money_rewards, entity_id)
    account = store.accounts[reward["account_id"]]

    # State (priority 7): reward PENDING.
    if reward["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING reward can be confirmed.")

    # KYC gate (priority 9): owning account VERIFIED.
    if account["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Owning account must be VERIFIED to confirm.")

    # Hold period (priority 12): clock at/after eligible_at.
    eligible_at = parse_iso8601(reward["eligible_at"])
    if store.now() < eligible_at:
        raise err("ERR_HOLD_PERIOD_ACTIVE", "Reward hold period has not elapsed.")

    reward["status"] = "CONFIRMED"
    touch(reward)
    # Conserved credit: cash += rebate, ledger row +rebate (PRD §3.10).
    account["cash_balance_cents"] = account["cash_balance_cents"] + reward["rebate_amount_cents"]
    create_cash_transaction(account["id"], "FOUND_MONEY", reward["rebate_amount_cents"], "CONFIRMED")
    return success(serialize(reward))


@bp.route("/found-money-rewards/<entity_id>/reverse", methods=["POST"])
def reverse_reward(entity_id):
    require_auth({"PlatformAdmin"})
    reward = fetch_or_404(store.found_money_rewards, entity_id)
    if reward["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING reward can be reversed.")
    reward["status"] = "REVERSED"
    touch(reward)
    return success(serialize(reward))
