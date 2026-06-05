"""Test-driving clock route (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.common import require_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(["PromoterAdmin"])()
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    # validate parseable
    try:
        db.parse_iso_dt(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO-8601 instant")
    db.set_current_utc(to_iso)
    return ok_object({}, 200)
