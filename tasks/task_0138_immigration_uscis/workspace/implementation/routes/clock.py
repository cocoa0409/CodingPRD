"""Clock advance + read endpoints (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_validation
from middleware import require_auth
from response import success
from services.case_engine import clock_advance_sweep
from utils import iso_now, parse_iso_datetime

from routes._helpers import get_json, require_string


bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth(["Supervisor"])
def advance_clock():
    body = get_json()
    to_str = require_string(body, "to")
    to_dt = parse_iso_datetime(to_str)
    if to_dt is None:
        raise err_validation("`to` must be a valid ISO 8601 UTC timestamp.")

    with store.lock:
        store.clock.set_to(to_dt)
        now = store.now()
        expired, auto_denied = clock_advance_sweep(now)

    return success({
        "now": iso_now(store.clock.logical_now()),
        "expired_rfes": expired,
        "auto_denied_cases": auto_denied,
    }, 200)


@bp.get("/_clock")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def read_clock():
    return success({"now": iso_now(store.clock.logical_now())}, 200)
