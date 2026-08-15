from flask import Blueprint

from db import store
from helpers import require_roles, body, reject_unknown, f_dt, ok, fmt_ts
from services import run_sweep

bp = Blueprint("clock", __name__)


@bp.route("/safety/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SafetyManager")
    b = body()
    reject_unknown(b, {"to_iso8601"})
    target = f_dt(b, "to_iso8601")
    store.clock = target
    run_sweep()
    return ok({"current_utc": fmt_ts(store.clock)})
