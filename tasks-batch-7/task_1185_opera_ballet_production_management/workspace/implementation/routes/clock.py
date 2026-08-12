"""Logical clock capability (PRD 2.5)."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok_object
from util import fmt_dt, json_body, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = json_body()
    dt = parse_dt(body.get("to_iso8601"), "to_iso8601")
    store.clock = dt
    return ok_object({"current_utc": fmt_dt(store.clock)})
