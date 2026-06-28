"""Operator logical clock + settlement sweep (PRD §2.5, §3.11)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from models import touch
from response import empty_response
from routes.common import get_json_body
from services.account import recompute_account, auto_meet_margin_calls
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


def settle_deposit(dep):
    """Move a PENDING deposit to SETTLED (PRD §3.1)."""
    acct = db.accounts.get(dep["account_id"])
    acct["settled_cash_cents"] += dep["amount_cents"]
    acct["instant_credit_cents"] -= dep["instant_credit_granted_cents"]
    dep["status"] = "SETTLED"
    touch(dep)
    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)


@bp.post("/_clock/advance")
def advance_clock():
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    body = get_json_body()

    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        target = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid instant")

    db.clock = target

    # run settlement sweep in the same request
    from services.settlement import run_sweep
    run_sweep()

    # advancing the clock may shift the PDT rolling window -> recompute accounts
    for acct in db.accounts.values():
        recompute_account(acct)

    return empty_response(200)
