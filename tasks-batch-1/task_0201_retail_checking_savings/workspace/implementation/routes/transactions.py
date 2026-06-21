"""Customer-initiated transactions + transaction reads — PRD §3.5."""
from flask import Blueprint, request, g

from db import db
from middleware import require_roles
from response import object_response
from models import public, touch
from services.validate import (
    get_body, require_fields, require_enum, require_positive_int_amount,
)
from services.resolve import get_account, get_transaction, require_account_owner
from services import ledger
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("transactions", __name__)

# Customer-initiated transaction types (PRD §3.5 endpoint description).
CUSTOMER_TXN_TYPES = {"DEPOSIT", "WITHDRAWAL", "CHECK_DEBIT"}

# Account states that accept a customer-initiated post (PRD §3.5).
# ACTIVE and DORMANT accept posting; FROZEN returns debits (handled in
# settle_debit) but credits also post; CLOSED/ESCHEATED reject as invalid state.
POSTABLE_STATES = {"ACTIVE", "DORMANT", "FROZEN"}


def serialize_txn(t):
    return public(t)


@bp.route("/accounts/<account_id>/transactions", methods=["POST"])
@require_roles("AccountHolder", "Teller")
def create_transaction(account_id):
    a = get_account(account_id)
    # Ownership gate for AccountHolder (priority 4).
    if g.user_role == "AccountHolder":
        require_account_owner(a, g.user_id)

    body = get_body()
    require_fields(body, "txn_type", "amount_cents")
    txn_type = require_enum(body, "txn_type", CUSTOMER_TXN_TYPES)
    amount = require_positive_int_amount(body["amount_cents"])

    check_number = body.get("check_number")
    if txn_type == "CHECK_DEBIT":
        require_fields(body, "check_number")
        check_number = body["check_number"]
    else:
        check_number = None

    # State gate (priority 5): only postable states accept transactions.
    if a["status"] not in POSTABLE_STATES:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Account is not in a state that accepts transactions")

    direction = ledger.direction_of(txn_type)

    # Build + store the PENDING transaction so balance derivation sees it.
    txn = ledger.make_transaction(account_id, txn_type, amount, check_number=check_number)
    db.transactions[txn["id"]] = txn

    was_dormant = a["status"] == "DORMANT"

    if direction == "CREDIT":
        # A credit always posts (unless account state forbids — only CLOSED/
        # ESCHEATED, already excluded). A FROZEN account still accepts credits.
        ledger.mark_posted(txn)
        # Customer-initiated DEPOSIT refreshes activity and reactivates dormancy.
        if txn_type in ledger.CUSTOMER_ACTIVITY_TYPES:
            ledger.touch_activity(a)
            if was_dormant:
                a["status"] = "ACTIVE"
            touch(a)
    else:
        ledger.settle_debit(a, txn, is_customer_initiated=True)
        # Customer-initiated debit (WITHDRAWAL/CHECK_DEBIT) refreshes activity for
        # any terminal outcome (POSTED/RETURNED/STOPPED) and a DEPOSIT/WITHDRAWAL
        # reactivates a dormant account.
        if txn_type in ledger.CUSTOMER_ACTIVITY_TYPES:
            ledger.touch_activity(a)
            # Only DEPOSIT/WITHDRAWAL reactivate (PRD §3.7); WITHDRAWAL qualifies.
            if was_dormant and txn_type == "WITHDRAWAL":
                a["status"] = "ACTIVE"
            touch(a)

    return object_response(serialize_txn(txn), status=201)


@bp.route("/accounts/<account_id>/transactions", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def list_account_transactions(account_id):
    get_account(account_id)
    status = request.args.get("status")
    txn_type = request.args.get("txn_type")
    rows = [t for t in db.transactions.values() if t["account_id"] == account_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if txn_type is not None:
        rows = [t for t in rows if t["txn_type"] == txn_type]
    return paged_list(rows, serializer=serialize_txn)


@bp.route("/transactions/<txn_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def get_one(txn_id):
    t = get_transaction(txn_id)
    return object_response(serialize_txn(t))


@bp.route("/transactions", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_transactions():
    ach_origination_id = request.args.get("ach_origination_id")
    account_id = request.args.get("account_id")
    rows = list(db.transactions.values())
    if ach_origination_id is not None:
        rows = [t for t in rows if t["ach_origination_id"] == ach_origination_id]
    if account_id is not None:
        rows = [t for t in rows if t["account_id"] == account_id]
    return paged_list(rows, serializer=serialize_txn)
