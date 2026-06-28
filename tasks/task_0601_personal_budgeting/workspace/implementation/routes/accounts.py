"""Account routes: link, get, list, archive."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_enum, opt_int,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_account
from services.reconcile import recompute_net_worth

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"DEPOSITORY", "CREDIT", "LOAN", "INVESTMENT"}


@bp.route("/households/<household_id>/accounts", methods=["POST"])
@require_roles("HouseholdOwner", "PlatformAdmin")
def link_account(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    institution_name = require_str(body, "institution_name")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    opening = opt_int(body, "opening_balance_cents", 0)

    with lock:
        aid = new_id()
        ts = now_ts()
        acc = {
            "id": aid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "institution_name": institution_name,
            "account_type": account_type,
            "cleared_balance_cents": opening,
            "available_balance_cents": opening,
            "opening_balance_cents": opening,
            "status": "LINKED",
        }
        db.accounts[aid] = acc
        recompute_net_worth(h)
    return success(serializers.account(acc), status=201)


@bp.route("/households/accounts/<account_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_account_route(account_id):
    a = get_account(account_id)
    enforce_household_access(a["household_id"])
    return success(serializers.account(a), status=200)


@bp.route("/households/accounts", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_accounts():
    household_id = request.args.get("household_id")
    status = request.args.get("status")
    items = list(db.accounts.values())
    if household_id is not None:
        items = [a for a in items if a["household_id"] == household_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate_and_respond(items, serializers.account)


@bp.route("/households/<household_id>/accounts/<account_id>/archive", methods=["POST"])
@require_roles("HouseholdOwner")
def archive_account(household_id, account_id):
    h = get_household(household_id)
    a = get_account(account_id)
    enforce_household_access(household_id)
    if a["household_id"] != household_id:
        raise errors.not_found("Account not found in household")

    # State: must be LINKED to archive.
    if a["status"] != "LINKED":
        raise errors.invalid_state("Account is not LINKED")

    # Pending-transactions guard.
    has_pending = any(t["account_id"] == account_id and t["status"] == "PENDING"
                      for t in db.transactions.values())
    if has_pending:
        raise errors.ApiError(errors.ERR_PENDING_TRANSACTIONS_EXIST, 409,
                              "Account still has PENDING transactions")

    with lock:
        a["status"] = "ARCHIVED"
        a["updated_at"] = now_ts()
        a["version"] += 1
        recompute_net_worth(h)
    return success(serializers.account(a), status=200)
