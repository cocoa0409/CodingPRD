"""Distribution: request, list, clear, deny, substantiate, reverse (PRD §3.8).

Two-person control: the holder requests; an admin clears/denies; substantiation
must be performed by an admin whose X-User-ID differs from cleared_by_user_id.
"""
from flask import Blueprint

import serializers
from db import db, stamp_create, touch
from errors import err
from helpers import (get_json_body, paginate, qarg, require_enum,
                     require_positive_int, require_string)
from lookups import (get_account, get_distribution, assert_account_owner)
from middleware import caller, require_role
from response import success

bp = Blueprint("distributions", __name__)


@bp.route("/hsa/accounts/<account_id>/distributions", methods=["POST"])
def request_distribution(account_id):
    user_id, role = caller()
    require_role(role, {"Accountholder"})
    account = get_account(account_id)
    assert_account_owner(account, user_id)
    body = get_json_body()
    method = require_enum(body, "method", {"DEBIT_CARD", "REIMBURSEMENT"})
    amount = require_positive_int(body, "amount_cents")
    card_id = require_string(body, "card_id", required=False)
    # For reimbursement the card_id is null.
    if method != "DEBIT_CARD":
        card_id = None

    o = {
        "account_id": account_id,
        "method": method,
        "amount_cents": amount,
        "card_id": card_id,
        "substantiation_status": "UNSUBSTANTIATED",
        "status": "REQUESTED",
        "receipt_id": None,
        "cleared_by_user_id": None,
    }
    stamp_create(o)
    db.distributions[o["id"]] = o
    return success(serializers.distribution(o), status=201)


@bp.route("/hsa/accounts/<account_id>/distributions", methods=["GET"])
def list_distributions(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    status_filter = qarg("status")
    subst_filter = qarg("substantiation_status")
    items = [
        d for d in db.distributions.values()
        if d["account_id"] == account_id
        and (status_filter is None or d["status"] == status_filter)
        and (subst_filter is None or d["substantiation_status"] == subst_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.distribution(d) for d in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/distributions/<distribution_id>/clear", methods=["POST"])
def clear_distribution(account_id, distribution_id):
    user_id, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    dist = get_distribution(account_id, distribution_id)

    # Only from REQUESTED.
    if dist["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Distribution is not REQUESTED")
    # Account must be ACTIVE.
    if account["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    # Sufficient cash.
    if account["cash_balance_cents"] < dist["amount_cents"]:
        raise err("ERR_INSUFFICIENT_CASH", "Insufficient cash to clear")
    # DEBIT_CARD: referenced card must be ACTIVE at clear time.
    if dist["method"] == "DEBIT_CARD":
        card = db.debit_cards.get(dist["card_id"])
        if (card is None or card["account_id"] != account_id
                or card["status"] != "ACTIVE"):
            raise err("ERR_CARD_NOT_ACTIVE", "Referenced card is not ACTIVE")

    dist["status"] = "CLEARED"
    dist["cleared_by_user_id"] = user_id
    touch(dist)
    account["cash_balance_cents"] -= dist["amount_cents"]
    touch(account)
    return success(serializers.distribution(dist), status=200)


@bp.route("/hsa/accounts/<account_id>/distributions/<distribution_id>/deny", methods=["POST"])
def deny_distribution(account_id, distribution_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    get_account(account_id)
    dist = get_distribution(account_id, distribution_id)
    if dist["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Distribution is not REQUESTED")
    dist["status"] = "DENIED"
    touch(dist)
    return success(serializers.distribution(dist), status=200)


@bp.route("/hsa/accounts/<account_id>/distributions/<distribution_id>/substantiate", methods=["POST"])
def substantiate_distribution(account_id, distribution_id):
    user_id, role = caller()
    require_role(role, {"AccountAdmin"})
    get_account(account_id)
    dist = get_distribution(account_id, distribution_id)
    body = get_json_body()
    receipt_id = require_string(body, "receipt_id", required=False)

    # State: must be CLEARED.
    if dist["status"] != "CLEARED":
        raise err("ERR_INVALID_STATE", "Distribution is not CLEARED")
    # Must still be UNSUBSTANTIATED.
    if dist["substantiation_status"] != "UNSUBSTANTIATED":
        raise err("ERR_ALREADY_SUBSTANTIATED", "Distribution already substantiated")
    # Segregation of duties: acting admin must differ from cleared_by_user_id.
    if user_id == dist["cleared_by_user_id"]:
        raise err("ERR_SEGREGATION_VIOLATION", "Same operator cleared and substantiated")

    receipt = None
    if receipt_id is not None:
        receipt = db.receipts.get(receipt_id)
        # Must be VAULTED and belong to this account.
        if (receipt is None or receipt["status"] != "VAULTED"
                or receipt["account_id"] != account_id):
            raise err("ERR_RECEIPT_NOT_AVAILABLE", "Receipt not available")
        # Must cover the distribution amount.
        if receipt["amount_cents"] < dist["amount_cents"]:
            raise err("ERR_RECEIPT_UNDERFUNDED", "Receipt does not cover distribution amount")

    # Substantiation outcome: QUALIFIED when a receipt with is_qualified_medical
    # is attached; NONQUALIFIED otherwise.
    if receipt is not None and receipt["is_qualified_medical"] is True:
        dist["substantiation_status"] = "QUALIFIED"
    else:
        dist["substantiation_status"] = "NONQUALIFIED"

    if receipt is not None:
        receipt["status"] = "CONSUMED"
        receipt["distribution_id"] = dist["id"]
        touch(receipt)
        dist["receipt_id"] = receipt["id"]

    touch(dist)
    return success(serializers.distribution(dist), status=200)


@bp.route("/hsa/accounts/<account_id>/distributions/<distribution_id>/reverse", methods=["POST"])
def reverse_distribution(account_id, distribution_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    dist = get_distribution(account_id, distribution_id)
    if dist["status"] != "CLEARED":
        raise err("ERR_INVALID_STATE", "Distribution is not CLEARED")
    dist["status"] = "REVERSED"
    account["cash_balance_cents"] += dist["amount_cents"]
    # Release a consumed receipt back to VAULTED.
    if dist["receipt_id"] is not None:
        receipt = db.receipts.get(dist["receipt_id"])
        if receipt is not None and receipt["status"] == "CONSUMED":
            receipt["status"] = "VAULTED"
            receipt["distribution_id"] = None
            touch(receipt)
    touch(dist)
    touch(account)
    return success(serializers.distribution(dist), status=200)
