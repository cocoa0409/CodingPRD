"""Test-driving logical clock endpoint."""
from flask import Blueprint

import db
from db import clock, _parse_iso, _format_iso
from middleware import get_auth, require_roles
from response import success_object
from errors import raise_err, ERR_INVALID_REQUEST
from services.core import get_body, check_unknown_fields
from services.sweeps import run_sweeps

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["to_iso8601"])
    require_roles(role, ("BoardAdmin",))
    to = body.get("to_iso8601")
    if not isinstance(to, str) or not to:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = _parse_iso(to)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO8601 UTC")
    clock.set(dt)
    swept = run_sweeps()
    return success_object({
        "current_utc": clock.now_iso(),
        "swept_counts": swept,
    })
