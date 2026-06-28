"""Transaction routes: ingest, get, list, post, recategorize, remove."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_int, opt_str, enforce_household_access,
                     paginate_and_respond)
from lookups import get_account, get_transaction, get_household, get_category
from services.reconcile import (recompute_account_balances, recompute_net_worth,
                                recompute_category, recompute_posture, touch)
from services.categorize import auto_categorize

bp = Blueprint("transactions", __name__)


def _household_for_account(acc):
    return db.households.get(acc["household_id"])


@bp.route("/accounts/<account_id>/transactions", methods=["POST"])
@require_roles("PlatformAdmin")
def ingest_transaction(account_id):
    acc = get_account(account_id)
    household = _household_for_account(acc)
    body = get_body()
    amount = require_int(body, "amount_cents")
    merchant = body.get("merchant_name")
    if merchant is None or not isinstance(merchant, str) or merchant == "":
        raise errors.invalid_request("merchant_name must be a non-empty string")
    category_id = opt_str(body, "budget_category_id", None)

    # State / account-status guard: account must be LINKED.
    if acc["status"] != "LINKED":
        raise errors.ApiError(errors.ERR_ACCOUNT_ARCHIVED, 409,
                              "Account is ARCHIVED")
    # Frozen-posture guard (spend-affecting write).
    if household and household["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")

    # Body reference: budget_category_id must exist and belong to same household.
    if category_id is not None:
        cat = db.budget_categories.get(category_id)
        if cat is None or cat["household_id"] != acc["household_id"]:
            raise errors.reference_not_found("budget_category_id not found in household")

    with lock:
        tid = new_id()
        ts = now_ts()
        txn = {
            "id": tid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "account_id": account_id,
            "budget_category_id": category_id,
            "amount_cents": amount,
            "merchant_name": merchant,
            "posted_period_id": None,
            "status": "PENDING",
        }
        db.transactions[tid] = txn
        recompute_account_balances(acc)
        if household:
            recompute_net_worth(household)
    return success(serializers.transaction(txn), status=201)


@bp.route("/households/transactions/<txn_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_transaction_route(txn_id):
    t = get_transaction(txn_id)
    acc = db.accounts.get(t["account_id"])
    if acc is not None:
        enforce_household_access(acc["household_id"])
    return success(serializers.transaction(t), status=200)


@bp.route("/households/transactions", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_transactions():
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    budget_category_id = request.args.get("budget_category_id")
    posted_period_id = request.args.get("posted_period_id")
    items = list(db.transactions.values())
    if account_id is not None:
        items = [t for t in items if t["account_id"] == account_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if budget_category_id is not None:
        items = [t for t in items if t.get("budget_category_id") == budget_category_id]
    if posted_period_id is not None:
        items = [t for t in items if t.get("posted_period_id") == posted_period_id]
    return paginate_and_respond(items, serializers.transaction)


@bp.route("/accounts/<account_id>/transactions/<txn_id>/post", methods=["POST"])
@require_roles("PlatformAdmin")
def post_transaction(account_id, txn_id):
    acc = get_account(account_id)
    txn = get_transaction(txn_id)
    if txn["account_id"] != account_id:
        raise errors.not_found("Transaction not found on account")
    household = _household_for_account(acc)

    # State: transition PENDING -> POSTED only defined from PENDING.
    if txn["status"] != "PENDING":
        raise errors.invalid_state("Transaction is not PENDING")
    # Account must be LINKED.
    if acc["status"] != "LINKED":
        raise errors.ApiError(errors.ERR_ACCOUNT_ARCHIVED, 409, "Account is ARCHIVED")
    # Frozen guard.
    if household and household["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")

    with lock:
        txn["status"] = "POSTED"
        touch(txn)
        # Auto-categorize if uncategorized.
        if txn.get("budget_category_id") is None and household:
            auto_categorize(txn, household)
        # If categorized, set posted_period and recompute its envelope.
        if txn.get("budget_category_id") is not None and household:
            txn["posted_period_id"] = household.get("current_period_id")
            cat = db.budget_categories.get(txn["budget_category_id"])
            if cat is not None:
                recompute_category(cat)
        recompute_account_balances(acc)
        if household:
            recompute_net_worth(household)
            recompute_posture(household)
    return success(serializers.transaction(txn), status=200)


@bp.route("/accounts/<account_id>/transactions/<txn_id>/recategorize", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def recategorize_transaction(account_id, txn_id):
    acc = get_account(account_id)
    txn = get_transaction(txn_id)
    if txn["account_id"] != account_id:
        raise errors.not_found("Transaction not found on account")
    household = _household_for_account(acc)
    enforce_household_access(acc["household_id"])

    body = get_body()
    new_cat_id = body.get("budget_category_id")
    if new_cat_id is None or not isinstance(new_cat_id, str) or new_cat_id == "":
        raise errors.invalid_request("budget_category_id is required")

    # Reference existence + same household.
    target = db.budget_categories.get(new_cat_id)
    if target is None or target["household_id"] != acc["household_id"]:
        raise errors.reference_not_found("budget_category_id not found in household")

    # State: recategorize defined only from POSTED.
    if txn["status"] != "POSTED":
        raise errors.invalid_state("Transaction is not POSTED")
    # Frozen guard.
    if household and household["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")
    # Target category must belong to current OPEN period.
    cur = household.get("current_period_id") if household else None
    if target["budget_period_id"] != cur:
        raise errors.ApiError(errors.ERR_CATEGORY_PERIOD_MISMATCH, 409,
                              "Target category not in current period")

    with lock:
        old_cat_id = txn.get("budget_category_id")
        txn["budget_category_id"] = new_cat_id
        txn["posted_period_id"] = cur
        touch(txn)
        if old_cat_id is not None and old_cat_id != new_cat_id:
            old_cat = db.budget_categories.get(old_cat_id)
            if old_cat is not None:
                recompute_category(old_cat)
        recompute_category(target)
        if household:
            recompute_posture(household)
    return success(serializers.transaction(txn), status=200)


@bp.route("/accounts/<account_id>/transactions/<txn_id>/remove", methods=["POST"])
@require_roles("PlatformAdmin")
def remove_transaction(account_id, txn_id):
    acc = get_account(account_id)
    txn = get_transaction(txn_id)
    if txn["account_id"] != account_id:
        raise errors.not_found("Transaction not found on account")
    household = _household_for_account(acc)

    # State: removable from PENDING or POSTED.
    if txn["status"] not in ("PENDING", "POSTED"):
        raise errors.invalid_state("Transaction is already REMOVED")
    # Frozen guard.
    if household and household["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")

    prev_status = txn["status"]
    cat_id = txn.get("budget_category_id")

    with lock:
        txn["status"] = "REMOVED"
        touch(txn)
        if prev_status == "POSTED":
            if cat_id is not None:
                cat = db.budget_categories.get(cat_id)
                if cat is not None:
                    recompute_category(cat)
            recompute_account_balances(acc)
            if household:
                recompute_net_worth(household)
                recompute_posture(household)
        else:
            # PENDING removed: only available balance + projected net worth move.
            recompute_account_balances(acc)
            if household:
                recompute_net_worth(household)
    return success(serializers.transaction(txn), status=200)
