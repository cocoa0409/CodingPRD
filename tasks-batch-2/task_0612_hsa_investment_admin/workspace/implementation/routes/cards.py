"""DebitCard: issue, list, activate, suspend, close (PRD §3.6).

Lifecycle: ISSUED -> ACTIVE -> {SUSPENDED <-> ACTIVE} -> CLOSED.
Activating requires lifecycle_status ACTIVE only when activating from ISSUED.
"""
from flask import Blueprint

import serializers
from db import db, stamp_create, touch
from errors import err
from helpers import get_json_body, paginate, qarg, require_string
from lookups import get_account, get_card, assert_account_owner
from middleware import caller, require_role
from response import success

bp = Blueprint("cards", __name__)


@bp.route("/hsa/accounts/<account_id>/cards", methods=["POST"])
def issue_card(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    account = get_account(account_id)
    body = get_json_body()
    last_four = require_string(body, "last_four")
    o = {
        "account_id": account_id,
        "last_four": last_four,
        "status": "ISSUED",
    }
    stamp_create(o)
    db.debit_cards[o["id"]] = o
    return success(serializers.debit_card(o), status=201)


@bp.route("/hsa/accounts/<account_id>/cards", methods=["GET"])
def list_cards(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    status_filter = qarg("status")
    items = [
        c for c in db.debit_cards.values()
        if c["account_id"] == account_id
        and (status_filter is None or c["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.debit_card(c) for c in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/cards/<card_id>/activate", methods=["POST"])
def activate_card(account_id, card_id):
    user_id, role = caller()
    require_role(role, {"Accountholder"})
    account = get_account(account_id)
    assert_account_owner(account, user_id)
    card = get_card(account_id, card_id)
    # Permitted from ISSUED or SUSPENDED. From ISSUED, account must be ACTIVE.
    if card["status"] == "ISSUED":
        if account["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    elif card["status"] == "SUSPENDED":
        pass
    else:
        raise err("ERR_INVALID_STATE", "Card cannot be activated from its current state")
    card["status"] = "ACTIVE"
    touch(card)
    return success(serializers.debit_card(card), status=200)


@bp.route("/hsa/accounts/<account_id>/cards/<card_id>/suspend", methods=["POST"])
def suspend_card(account_id, card_id):
    user_id, role = caller()
    require_role(role, {"Accountholder"})
    account = get_account(account_id)
    assert_account_owner(account, user_id)
    card = get_card(account_id, card_id)
    if card["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Card is not ACTIVE")
    card["status"] = "SUSPENDED"
    touch(card)
    return success(serializers.debit_card(card), status=200)


@bp.route("/hsa/accounts/<account_id>/cards/<card_id>/close", methods=["POST"])
def close_card(account_id, card_id):
    user_id, role = caller()
    require_role(role, {"Accountholder"})
    account = get_account(account_id)
    assert_account_owner(account, user_id)
    card = get_card(account_id, card_id)
    # Closing moves to CLOSED from ACTIVE or SUSPENDED; terminal.
    if card["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Card cannot be closed from its current state")
    card["status"] = "CLOSED"
    touch(card)
    return success(serializers.debit_card(card), status=200)
