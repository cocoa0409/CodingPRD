"""Admin routes: logical clock and the time-driven sweep."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok
from services import run_sweep
from util import get_body, req_datetime, fmt

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("TransportSupervisor")
    data = get_body()
    dt = req_datetime(data, "to_iso8601")
    store.clock = dt
    return ok({"current_utc": fmt(store.clock)})


@bp.post("/_sweeps/run")
def sweeps_run():
    require_roles("TransportSupervisor")
    return ok(run_sweep())
