"""Test-driving surface (PlatformAdmin only): pin the clock, seed a credit.

These are NOT auth-exempt — PRD §2.1 exempts only POST /accounts from auth; the
test-driving endpoints require a PlatformAdmin caller.
"""
from flask import Blueprint

import clock
import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles
from services import ledger

bp = Blueprint("testdriving", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    with db.lock:
        p = authenticate()
        require_roles(p, {"PlatformAdmin"})
        body = validate.get_json_body()
        to_iso = validate.require_str(body, "to_iso8601")
        try:
            dt = clock.parse_iso8601(to_iso)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
        db.set_clock(dt)
        return response.ok({})


@bp.route("/_ledger/seed_credit", methods=["POST"])
def seed_credit():
    with db.lock:
        p = authenticate()
        require_roles(p, {"PlatformAdmin"})
        body = validate.get_json_body()
        account_id = validate.require_str(body, "account_id")
        amount = validate.require_int(body, "amount_cents", minimum=1)
        memo = validate.optional_str(body, "memo", "")
        acct = db.accounts.get(account_id)
        if not acct:
            raise err("ERR_NOT_FOUND", "Account not found.")
        entry = ledger.post_ledger(account_id, "CREDIT", amount, "ADJUSTMENT", None, memo)
        ledger.recompute_account(acct)
        models.touch(acct)  # version bump must be observed by next withdrawal's OCC
        return response.ok(models.serialize(entry), 201)
