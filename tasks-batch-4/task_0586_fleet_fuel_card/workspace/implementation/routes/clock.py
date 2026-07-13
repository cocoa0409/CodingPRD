"""Test-driving logical clock (PRD §2.4)."""
from flask import Blueprint

import response
from db import db
from errors import err
from middleware import body, req_str, require_roles
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_current_utc():
    data = body()
    raw = req_str(data, "to_iso8601")
    try:
        parse_dt(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "Field 'to_iso8601' must be an ISO 8601 datetime.")
    db.clock.set(raw)
    return response.ok({"now": db.clock.now_iso()})
