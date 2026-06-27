"""Deposit endpoints (PRD §3.1, §4)."""
from flask import Blueprint

import constants
import errors
from db import db, new_id, created_ts
from middleware import get_identity, require_role, require_account_owner
from models import _base_full, account_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_account, get_deposit, paginate,
                           page_slice)
from services.account import recompute_account, auto_meet_margin_calls
from timeutil import add_business_days, iso

bp = Blueprint("deposits", __name__)


def _deposit_dict(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _outstanding_instant_credit(account_id):
    """Sum instant_credit_granted_cents over the account's PENDING deposits."""
    total = 0
    for dep in db.deposits.values():
        if dep["account_id"] == account_id and dep["status"] == "PENDING":
            total += dep["instant_credit_granted_cents"]
    return total


@bp.post("/accounts/<account_id>/deposits")
def create_deposit(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])
    body = get_json_body()

    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "amount_cents must be a positive integer")

    instant_eligible = body.get("instant_eligible", True)
    if not isinstance(instant_eligible, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "instant_eligible must be a boolean")

    # Instant-credit headroom check (PRD §3.1, business_fiscal priority 17)
    requested = amount if instant_eligible else 0
    outstanding = _outstanding_instant_credit(account_id)
    headroom = constants.INSTANT_CAP_CENTS - outstanding
    if requested > headroom:
        raise errors.err(errors.ERR_INSTANT_LIMIT_EXCEEDED,
                         "Requested instant credit exceeds remaining cap headroom")

    granted = requested

    rec = _base_full()
    rec.update({
        "account_id": account_id,
        "amount_cents": amount,
        "instant_eligible": instant_eligible,
        "instant_credit_granted_cents": granted,
        "status": "PENDING",
        "settles_on": iso(add_business_days(db.clock, 1)),
    })
    db.deposits[rec["id"]] = rec

    acct["instant_credit_cents"] += granted
    recompute_account(acct)
    touch(acct)  # creating the deposit increments Account.version by 1 (PRD §3.1)

    return object_response(_deposit_dict(rec), 201)


@bp.get("/accounts/<account_id>/deposits")
def list_deposits(account_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    status = paginate_status()
    items = [d for d in db.deposits.values() if d["account_id"] == account_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([_deposit_dict(d) for d in page], limit, offset, total)


def paginate_status():
    from flask import request
    return request.args.get("status")


@bp.post("/deposits/<deposit_id>/reverse")
def reverse_deposit(deposit_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    dep = get_deposit(deposit_id)

    if dep["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Deposit is not PENDING")

    acct = db.accounts.get(dep["account_id"])
    dep["status"] = "REVERSED"
    touch(dep)
    # claw back provisional credit (PRD §3.1)
    acct["instant_credit_cents"] -= dep["instant_credit_granted_cents"]
    recompute_account(acct)
    touch(acct)  # increments Account.version by 1
    return object_response(_deposit_dict(dep), 200)
