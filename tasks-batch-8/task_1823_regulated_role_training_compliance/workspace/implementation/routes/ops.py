"""Test-driving endpoints: the logical clock and the deterministic sweep."""
from flask import Blueprint

from db import store
from middleware import require_roles
from response import get_body, req_dt, success
from services import run_sweep
from util import fmt_dt

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ComplianceAdmin")
    body = get_body()
    to = req_dt(body, "to_iso8601")
    store.clock = to
    return success({"current_utc": fmt_dt(store.clock)})


@bp.post("/_sweeps/run")
def sweeps_run():
    require_roles("ComplianceAdmin")
    return success(run_sweep())
