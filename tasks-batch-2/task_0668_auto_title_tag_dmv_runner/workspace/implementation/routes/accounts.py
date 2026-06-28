"""Account & payment endpoints (PRD §3.1, §3.7; scaffold §1.5)."""

from flask import Blueprint, g, request

import errors
import repo
from db import db
from domain import (active_schedule_for_state, recompute_account_balance,
                    settled_quote_for_transaction)
from helpers import (get_json_body, require_str, require_int, opt_bool, opt_int,
                     require_enum, parse_pagination, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import account_out, payment_out

bp = Blueprint("accounts", __name__)


@bp.route("/dmv/accounts", methods=["POST"])
@require_roles("PlatformAdmin")
def create_account():
    body = get_json_body()
    account_type = require_enum(body, "account_type", {"RETAIL", "FLEET"})
    legal_name = require_str(body, "legal_name")
    state_code = require_str(body, "state_code")
    credit_terms = opt_bool(body, "credit_terms", False)
    credit_limit_cents = opt_int(body, "credit_limit_cents", 0)
    if credit_limit_cents < 0:
        raise errors.validation("credit_limit_cents must be >= 0")

    # state_code must match the state_code of an existing fee schedule (§3.1).
    if active_schedule_for_state(state_code) is None:
        raise errors.invalid_request(
            "state_code must match the state_code of an existing fee schedule"
        )

    rec = repo.make_account(account_type, legal_name, state_code, credit_terms,
                            credit_limit_cents)
    return success(account_out(rec), 201)


@bp.route("/dmv/accounts/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def get_account(aid):
    acct = db.accounts.get(aid)
    if acct is None:
        raise errors.not_found("account not found")
    # AccountHolder may read only their own account.
    if g.user_role == "AccountHolder" and g.user_id != acct["id"]:
        raise errors.not_resource_owner("AccountHolder may only read their own account")
    return success(account_out(acct), 200)


@bp.route("/dmv/accounts/<aid>/reinstate", methods=["POST"])
@require_roles("PlatformAdmin")
def reinstate_account(aid):
    acct = db.accounts.get(aid)
    if acct is None:
        raise errors.not_found("account not found")
    if acct["status"] != "SUSPENDED":
        raise errors.invalid_state("account is not SUSPENDED")
    acct["status"] = "ACTIVE"
    repo.bump(acct)
    return success(account_out(acct), 200)


@bp.route("/dmv/accounts/<aid>/payments", methods=["POST"])
@require_roles("PlatformAdmin", "AccountHolder")
def create_payment(aid):
    body = get_json_body()
    # Existence of path account first (priority 3).
    acct = db.accounts.get(aid)
    if acct is None:
        raise errors.not_found("account not found")

    transaction_id = require_str(body, "transaction_id")
    amount_cents = require_int(body, "amount_cents")
    kind = require_enum(body, "kind", {"CHARGE", "REFUND"})

    # Body FK existence (priority 3).
    txn = db.transactions.get(transaction_id)
    if txn is None:
        raise errors.not_found("transaction not found")

    # Ownership for AccountHolder (priority 4): X-User-ID == target account id.
    if g.user_role == "AccountHolder" and g.user_id != acct["id"]:
        raise errors.not_resource_owner("AccountHolder may only pay on their own account")

    # amount must be >= 1 (typed constraint).
    if amount_cents < 1:
        raise errors.validation("amount_cents must be >= 1")

    # The referenced transaction must be COMPLETED, and amount must equal its
    # SETTLED FeeQuote.total_cents (priority 15).
    if txn["lifecycle_status"] != "COMPLETED":
        raise errors.payment_amount_mismatch(
            "referenced transaction must be COMPLETED"
        )
    settled = settled_quote_for_transaction(transaction_id)
    if settled is None or amount_cents != settled["total_cents"]:
        raise errors.payment_amount_mismatch(
            "amount_cents must equal the SETTLED FeeQuote total"
        )

    rec = repo.make_payment(acct["id"], transaction_id, amount_cents, kind)

    # Recompute balance; may clear SUSPENDED.
    recompute_account_balance(acct)
    if acct["outstanding_balance_cents"] <= acct["credit_limit_cents"] and acct["status"] == "SUSPENDED":
        # PRD §3.7: a payment "may clear a SUSPENDED status back toward
        # eligibility". Status only returns to ACTIVE via admin reinstate (§3.1),
        # so we do NOT auto-reactivate here; we leave reinstatement to the admin.
        pass
    repo.bump(acct)
    return success(payment_out(rec), 201)


@bp.route("/dmv/payments", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def list_payments():
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    transaction_id = request.args.get("transaction_id")
    items = list(db.payments.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if transaction_id is not None:
        items = [p for p in items if p["transaction_id"] == transaction_id]
    if g.user_role == "AccountHolder":
        items = [p for p in items if p["account_id"] == g.user_id]
    page, total = paginate(items, limit, offset)
    return list_success([payment_out(p) for p in page], limit, offset, total)


@bp.route("/dmv/payments/<pid>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise errors.not_found("payment not found")
    if g.user_role == "AccountHolder" and p["account_id"] != g.user_id:
        raise errors.not_resource_owner("AccountHolder may only read their own payments")
    return success(payment_out(p), 200)
