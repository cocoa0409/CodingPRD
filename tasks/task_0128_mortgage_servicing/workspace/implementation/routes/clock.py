"""Test-driving endpoints: clock advance + sweep."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_auth
from response import success
from services.loan_engine import run_sweep

from routes._helpers import get_json

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth(["PlatformAdmin"])
def advance_clock():
    body = get_json()
    days = body.get("days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise ApiError("ERR_INVALID_STATE", 409, "days must be a non-negative integer")
    with store.lock:
        store.clock.advance_days(days)
        run_sweep()
    return success({}, 200)


@bp.post("/_sweep/run")
@require_auth(["PlatformAdmin"])
def run_sweep_endpoint():
    with store.lock:
        run_sweep()
    return success({}, 200)
