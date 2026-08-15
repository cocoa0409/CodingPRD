"""Logical clock endpoint (PRD 2.5). Mounted outside /api."""

from flask import Blueprint

from db import store
from middleware import authenticate, require_roles, get_body, v_dt, fmt_dt
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_roles("PlatformAdmin")
    body = get_body()
    to = v_dt(body, "to_iso8601")
    store.clock = to
    return success({"current_utc": fmt_dt(store.clock)}, 200)
