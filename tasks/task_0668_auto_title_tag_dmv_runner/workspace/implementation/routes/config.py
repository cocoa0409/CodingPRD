"""Config / clock / admin test-driving endpoints (PRD §2.4, §3.1; scaffold §1.5).

All PlatformAdmin-only. The logical clock, fee-period advance, and the two
_inject test-driving endpoints live here.
"""

from flask import Blueprint, g

import errors
import repo
from clock import clock, parse_iso8601
from db import db
from helpers import get_json_body, require_int
from middleware import require_roles
from response import success
from serializers import account_out, transaction_out

bp = Blueprint("config", __name__)


@bp.route("/dmv/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or raw == "":
        raise errors.invalid_request("to_iso8601 is required")
    try:
        instant = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant")
    clock.set(instant)
    return success({}, 200)


@bp.route("/dmv/_fee-periods/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def advance_fee_period():
    # Reset every account's ytd_completed_count to 0; bump each account version.
    for acct in db.accounts.values():
        acct["ytd_completed_count"] = 0
        repo.bump(acct)
    return success({}, 200)


@bp.route("/dmv/_inject/account_counters", methods=["POST"])
@require_roles("PlatformAdmin")
def inject_account_counters():
    body = get_json_body()
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or account_id == "":
        raise errors.invalid_request("account_id is required")
    target = require_int(body, "ytd_completed_count")
    if target < 0:
        raise errors.validation("ytd_completed_count must be >= 0")
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("account not found")
    acct["ytd_completed_count"] = target
    repo.bump(acct)
    return success(account_out(acct), 200)


@bp.route("/dmv/_inject/rejection_round", methods=["POST"])
@require_roles("PlatformAdmin")
def inject_rejection_round():
    body = get_json_body()
    transaction_id = body.get("transaction_id")
    if not isinstance(transaction_id, str) or transaction_id == "":
        raise errors.invalid_request("transaction_id is required")
    target = require_int(body, "rejection_round")
    if target < 0:
        raise errors.validation("rejection_round must be >= 0")
    txn = db.transactions.get(transaction_id)
    if txn is None:
        raise errors.not_found("transaction not found")
    txn["rejection_round"] = target
    repo.bump(txn)
    return success(transaction_out(txn), 200)
