"""Test-driving logical clock route (PRD §2.6)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_roles
from response import ok_object
from services import clock as clock_svc
from services import helpers as h

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set")
def set_clock():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()
    now_iso8601 = h.require_string(body, "now_iso8601")

    # Validate it parses as an instant.
    try:
        clock_svc.to_dt(now_iso8601)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "now_iso8601 is not a valid ISO 8601 instant")

    db.logical_clock["now"] = now_iso8601
    return ok_object({"now_iso8601": now_iso8601}, 200)
