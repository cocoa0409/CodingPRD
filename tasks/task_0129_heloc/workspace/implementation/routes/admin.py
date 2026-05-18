"""PlatformAdmin-only test-driving endpoints: clock + sweeps."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_validation_failed
from middleware import require_auth
from response import success
from services.engine import run_annual_fee_sweep, run_billing_cycle_sweep
from utils import iso_now

from routes._helpers import get_int, get_json

bp = Blueprint("admin", __name__)


@bp.post("/_clock/advance")
@require_auth(["PlatformAdmin"], endpoint_key="POST /_clock/advance")
def advance_clock():
    body = get_json()
    seconds = get_int(body, "seconds", required=True)
    if seconds < 0:
        raise err_validation_failed("seconds must be a non-negative integer.")
    with store.lock:
        store.clock.advance_seconds(seconds)
        now = store.now()
    return success({"current_time": iso_now(now)}, 200)


@bp.post("/_sweep/billing-cycle")
@require_auth(["PlatformAdmin"], endpoint_key="POST /_sweep/billing-cycle")
def sweep_billing_cycle():
    with store.lock:
        result = run_billing_cycle_sweep()
    return success(result, 200)


@bp.post("/_sweep/annual-fees")
@require_auth(["PlatformAdmin"], endpoint_key="POST /_sweep/annual-fees")
def sweep_annual_fees():
    with store.lock:
        result = run_annual_fee_sweep()
    return success(result, 200)
