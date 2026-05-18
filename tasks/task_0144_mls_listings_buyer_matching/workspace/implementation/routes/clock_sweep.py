"""Test harness endpoints: /_clock/advance and /_sweep/run."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_state
from middleware import require_auth
from response import success
from routes._helpers import get_json, parse_required_iso
from services.sweep import run_sweep
from utils import iso_now


bp = Blueprint("clock_sweep", __name__)


@bp.post("/_clock/advance")
@require_auth(["MlsAdmin"])
def advance_clock():
    body = get_json()
    to_dt = parse_required_iso(
        body, "to", err_invalid_state("`to` is required and must be ISO 8601.")
    )
    now = store.clock.advance_to(to_dt)
    return success({"now": iso_now(now)}, 200)


@bp.post("/_sweep/run")
@require_auth(["MlsAdmin"])
def run_sweep_endpoint():
    with store.lock:
        result = run_sweep()
    return success(result, 200)
