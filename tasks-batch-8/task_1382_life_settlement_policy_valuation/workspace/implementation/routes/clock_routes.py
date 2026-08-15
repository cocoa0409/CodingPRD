"""POST /api/_clock/set_current_utc — the test-driving logical clock."""

from flask import Blueprint

from cascade import run_clock_transitions
from db import store
from middleware import auth, get_body, req, require_role, v_dt
from response import ok
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    target = v_dt(req(body, "to_iso8601"), "to_iso8601")
    store.clock = target
    run_clock_transitions()
    return ok({"current_utc": fmt_dt(store.clock)})
