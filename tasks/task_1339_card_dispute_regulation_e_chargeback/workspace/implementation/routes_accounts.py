"""Routes: card accounts and card transactions."""

from flask import Blueprint

import db
import errors
import middleware
from clock import parse_iso, iso_z
from helpers import (
    NETWORKS,
    TRANSACTION_TYPES,
    get_body,
    paginate,
    parse_pagination,
    serialize_account,
    serialize_transaction,
    sorted_by_creation,
    stamp_new,
    validate_body,
)
from middleware import require_cardholder_owns
from response import success_list, success_object
from state import CLOCK

bp = Blueprint("accounts", __name__)


@bp.route("/card-accounts", methods=["POST"])
def create_card_account():
    middleware.authenticate()
    middleware.require_roles("BankAdmin")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("cardholder_name", "string", True, None),
            ("initial_balance_cents", "int_nonneg", False, None),
        ],
    )
    initial = fields["initial_balance_cents"]
    if initial is None:
        initial = 0
    account = stamp_new(CLOCK)
    account.update(
        {
            "cardholder_name": fields["cardholder_name"],
            "opened_at": CLOCK.now_iso(),
            "status": "ACTIVE",
            "balance_cents": initial,
        }
    )
    db.card_accounts[account["id"]] = account
    return success_object(serialize_account(account), 201)


@bp.route("/card-accounts/<account_id>", methods=["GET"])
def get_card_account(account_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    account = db.card_accounts.get(account_id)
    if account is None:
        raise errors.not_found("CardAccount not found")
    require_cardholder_owns(account["id"])
    return success_object(serialize_account(account), 200)


@bp.route("/card-accounts/<account_id>/transactions", methods=["GET"])
def list_account_transactions(account_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    account = db.card_accounts.get(account_id)
    if account is None:
        raise errors.not_found("CardAccount not found")
    require_cardholder_owns(account["id"])
    limit, offset = parse_pagination()
    txns = [
        t for t in db.card_transactions.values() if t["card_account_id"] == account_id
    ]
    txns = sorted_by_creation(txns)
    page, total = paginate(txns, limit, offset)
    return success_list([serialize_transaction(t) for t in page], limit, offset, total)


@bp.route("/card-transactions", methods=["POST"])
def create_card_transaction():
    middleware.authenticate()
    middleware.require_roles("BankAdmin")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("card_account_id", "string", True, None),
            ("merchant_name", "string", True, None),
            ("amount_cents", "int", True, None),
            ("transaction_type", "string", True, sorted(TRANSACTION_TYPES)),
            ("network", "string", True, sorted(NETWORKS)),
            ("posted_at", "iso", True, None),
        ],
    )
    account = db.card_accounts.get(fields["card_account_id"])
    if account is None:
        raise errors.not_found("CardAccount not found")
    if account["status"] == "RESTRICTED":
        raise errors.account_restricted()
    posted_dt = parse_iso(fields["posted_at"])
    if posted_dt is None:
        raise errors.invalid_request("posted_at is not a valid ISO 8601 timestamp")
    txn = stamp_new(CLOCK)
    txn.update(
        {
            "card_account_id": account["id"],
            "merchant_name": fields["merchant_name"],
            "amount_cents": fields["amount_cents"],
            "transaction_type": fields["transaction_type"],
            "network": fields["network"],
            "posted_at": iso_z(posted_dt),
            "status": "POSTED",
        }
    )
    db.card_transactions[txn["id"]] = txn
    return success_object(serialize_transaction(txn), 201)
