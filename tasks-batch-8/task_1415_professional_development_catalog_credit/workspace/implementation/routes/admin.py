"""Logical clock and district ops checkpoint."""
from flask import Blueprint

from auth import require_role
from db import store
from envelope import ok, get_body
from services import ops_run
from validate import req_datetime

bp = Blueprint("admin", __name__)


@bp.post("/pd/_clock/set_current_utc")
def set_clock():
    require_role("PDCoordinator")
    body = get_body()
    to = req_datetime(body, "to_iso8601")
    store.clock = to
    return ok({}, 200)


@bp.post("/pd/ops-runs")
def run_ops():
    require_role("PDCoordinator")
    get_body()
    out = ops_run()
    return ok(out, 200)
