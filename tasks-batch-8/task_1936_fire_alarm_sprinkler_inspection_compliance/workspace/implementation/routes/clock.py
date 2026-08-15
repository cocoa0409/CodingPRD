"""Logical clock endpoint (PRD §2.5)."""

from flask import Blueprint

from db import store, fmt_ts
from middleware import require_roles, ROLE_FIRE_MARSHAL
from response import success_object
from util import get_body, check_unknown_fields, req_datetime
from services.sweep import run_daily_sweep

bp = Blueprint("clock", __name__)


@bp.route("/fire-compliance/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([ROLE_FIRE_MARSHAL])
    body = get_body()
    check_unknown_fields(body, {"to_iso8601"})
    to = req_datetime(body, "to_iso8601")
    store.clock.set(to)
    run_daily_sweep()
    return success_object({"current_utc": fmt_ts(store.now())})
