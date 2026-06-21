"""ContractorAccount endpoints (PRD §3.3, §3.7)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth, get_identity
from services.common import (
    new_record, require_body, req_str, req_int, touch, get_or_404,
)
from services.ledger import account_view, post_entry, recompute_balance
from response import object_response
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("contractor_accounts", __name__)


@bp.post("/rental-yard/contractor-accounts")
def create_account():
    require_auth({"YardManager"})
    body = require_body(get_json_body())
    company_name = req_str(body, "company_name", 1, 120)
    credit_limit = req_int(body, "credit_limit_cents", 0)

    with LOCK:
        rec = new_record({
            "company_name": company_name,
            "credit_limit_cents": credit_limit,
            "outstanding_balance_cents": 0,
            "account_status": "ACTIVE",
            "open_reservation_count": 0,
        })
        DB.contractor_accounts[rec["id"]] = rec
    return single_response(rec, 201, view_fn=account_view)


@bp.get("/rental-yard/contractor-accounts/<rid>")
def get_account(rid):
    # Public GET? PRD §2.1: reads are public. But §2.1 also states a Contractor
    # reading their own account must own it. Apply ownership only when the caller
    # presents the Contractor role (GET carries no mandatory auth otherwise).
    rec = get_or_404(DB.contractor_accounts, rid)
    user_id, role = get_identity()
    if role == "Contractor" and user_id is not None and user_id != rid:
        raise errors.not_account_owner()
    return single_response(rec, view_fn=account_view)


@bp.get("/rental-yard/contractor-accounts")
def list_accounts():
    account_status = request.args.get("account_status")
    accounts = DB.contractor_accounts.values()
    if account_status is not None:
        accounts = [a for a in accounts if a["account_status"] == account_status]
    return list_response(accounts, view_fn=account_view)


@bp.post("/rental-yard/contractor-accounts/<rid>/suspend")
def suspend_account(rid):
    require_auth({"YardManager"})
    with LOCK:
        rec = get_or_404(DB.contractor_accounts, rid)
        rec["account_status"] = "SUSPENDED"
        touch(rec)
    return single_response(rec, view_fn=account_view)


@bp.post("/rental-yard/contractor-accounts/<rid>/payments")
def record_payment(rid):
    user_id, role = require_auth({"YardManager", "Contractor"})
    with LOCK:
        # Existence first (PRD §2.5).
        account = get_or_404(DB.contractor_accounts, rid)
        # Ownership for Contractor (PRD §2.1).
        if role == "Contractor" and user_id != rid:
            raise errors.not_account_owner()
        body = require_body(get_json_body())
        amount = body.get("amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise errors.invalid_request("Field 'amount_cents' must be an integer.")
        # Payment amount must be strictly negative (PRD §3.3).
        if amount >= 0:
            raise errors.payment_not_negative()
        entry = post_entry(rid, "PAYMENT", amount, rental_agreement_id=None)
        # outstanding_balance_cents recomputed on insert (PRD §3.3 / §2.9).
        recompute_balance(rid)
    # The payment endpoint returns the AccountLedgerEntry (output: AccountLedgerEntry).
    return object_response(_serialize_entry(entry), 201)


def _serialize_entry(entry):
    from services.common import serialize
    return serialize(entry)


@bp.get("/rental-yard/contractor-accounts/<rid>/ledger")
def list_account_ledger(rid):
    account = get_or_404(DB.contractor_accounts, rid)
    user_id, role = get_identity()
    if role == "Contractor" and user_id is not None and user_id != rid:
        raise errors.not_account_owner()
    entry_type = request.args.get("entry_type")
    entries = [e for e in DB.ledger_entries.values()
               if e["contractor_account_id"] == rid]
    if entry_type is not None:
        entries = [e for e in entries if e["entry_type"] == entry_type]
    return list_response(entries)


@bp.get("/rental-yard/contractor-accounts/<rid>/reservations")
def list_account_reservations(rid):
    account = get_or_404(DB.contractor_accounts, rid)
    user_id, role = get_identity()
    if role == "Contractor" and user_id is not None and user_id != rid:
        raise errors.not_account_owner()
    reservation_state = request.args.get("reservation_state")
    reservations = [r for r in DB.reservations.values()
                    if r["contractor_account_id"] == rid]
    if reservation_state is not None:
        reservations = [r for r in reservations
                        if r["reservation_state"] == reservation_state]
    return list_response(reservations)
