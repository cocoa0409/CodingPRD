"""Test-driving logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

import clock
import response
import validate as v
from middleware import ALL_ROLES, require

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
@require(*ALL_ROLES)
def set_current_utc():
    body = v.body()
    _raw, parsed = v.req_instant(body, "to_iso8601")
    updated = clock.set_now(parsed)
    return response.ok({"current_utc": clock.fmt_instant(updated)})
