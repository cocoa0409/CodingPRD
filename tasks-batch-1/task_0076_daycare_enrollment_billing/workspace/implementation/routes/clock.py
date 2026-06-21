"""Test-driving clock endpoint (PRD §2.10)."""
from __future__ import annotations

from datetime import datetime, timezone
from flask import Blueprint

from db import clock
from middleware import require_roles
from response import ok_object
from common import get_body, require_str
from errors import APIError, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("CenterDirector")
def set_current_utc():
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    s = to_iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    clock.set(dt)
    return ok_object({}, 200)
