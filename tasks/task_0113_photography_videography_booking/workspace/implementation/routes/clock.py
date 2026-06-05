"""Test-driving logical clock (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, ROLE_STUDIO_ADMIN
from response import ok_object
from routes._helpers import get_body, require_str
from services import calculations as calc

bp = Blueprint("clock", __name__)


@bp.post("/studio/_clock/set_current_utc")
def set_clock():
    require_auth([ROLE_STUDIO_ADMIN])
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        calc.parse_iso(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "to_iso8601 must be a valid ISO-8601 instant")
    db.set_clock_iso(to_iso)
    return ok_object({"current_utc": to_iso}, 200)
