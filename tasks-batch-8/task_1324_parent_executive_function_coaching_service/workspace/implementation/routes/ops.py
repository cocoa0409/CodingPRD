"""Logical clock control and daily operations sweep."""
from flask import Blueprint

import db
import middleware as mw
from middleware import get_auth, require_roles, get_body, require_fields, parse_dt
from response import success_object
from services import sweep as sweep_svc

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_dt(body["to_iso8601"], "to_iso8601")
    return success_object({"current_utc": db.now_iso()}, 200)


@bp.post("/admin/run-daily-sweep")
def run_sweep():
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    summary = sweep_svc.run_daily_sweep()
    return success_object(summary, 200)
