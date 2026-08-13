"""Test-driving logical clock endpoint (PlatformAdmin only)."""
from flask import Blueprint

from db import store
from middleware import require_roles
from response import success
from services import workflow
from validate import get_body, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    raw = body.get("to_iso8601")
    dt = v_dt(body, "to_iso8601")
    require_roles("PlatformAdmin")
    with store.lock:
        store.clock_dt = dt
        store.clock_raw = raw
        # Advancing the clock triggers the overdue / escalation / expiry sweep.
        workflow.run_sweep()
        return success({"current_utc": store.clock_raw})
