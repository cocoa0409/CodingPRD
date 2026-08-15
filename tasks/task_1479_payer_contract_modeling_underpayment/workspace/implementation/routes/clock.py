"""Test-driving logical clock endpoint (PRD §2.4, §3.9)."""

from flask import Blueprint

import db as _db
from db import parse_clock
from errors import err_invalid_request
from middleware import require_roles
from response import success_object
from services.sweep import run_clock_sweep
from services.validation import body, reject_unknown

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles(["SystemAdmin"])
    data = body()
    reject_unknown(data, {"to_iso8601"})
    raw = data.get("to_iso8601")
    if raw is None:
        raise err_invalid_request("Missing required field: to_iso8601")
    try:
        dt = parse_clock(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be an ISO 8601 UTC datetime")
    _db.store.clock = dt
    summary = run_clock_sweep()
    out = {"current_utc": _db.clock_iso()}
    out.update(summary)
    return success_object(out)
