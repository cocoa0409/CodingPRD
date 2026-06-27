"""Logical clock administration (PRD §2.10)."""
from flask import Blueprint

import clock as clock_module
import helpers as h
from middleware import authenticate, authorize
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = h.get_body()
    to_iso = h.require_str(body, "to_iso8601")
    dt = h.parse_iso(to_iso, "to_iso8601")
    clock_module.set_now(dt)
    # output: null -> empty data object (PRD §2.2: 2xx with no data -> {})
    return success({}, status=200)
