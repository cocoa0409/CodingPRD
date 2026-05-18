"""Dividend recording endpoint."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_fk_not_found, err_invalid_state
from middleware import require_auth
from response import success
from routes._helpers import get_json
from routes.accounts import enforce_account_active, get_account_or_404
from services.engine import record_dividend
from services.serializers import serialize_dividend_event

bp = Blueprint("dividends", __name__)


@bp.post("/accounts/<account_id>/dividends")
@require_auth(["Advisor", "system"])
def post_dividend(account_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    body = get_json()
    sid = body.get("security_id")
    amount = body.get("amount_cents")
    if not isinstance(sid, str) or sid not in store.securities:
        raise err_fk_not_found("security_id not found.")
    sec = store.securities[sid]
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int):
        raise err_invalid_state("amount_cents must be a positive integer.")
    if amount <= 0:
        raise err_invalid_state("amount_cents must be > 0.")
    with store.lock:
        ev, _ = record_dividend(a, sec, amount)
    return success(serialize_dividend_event(ev), 201)
