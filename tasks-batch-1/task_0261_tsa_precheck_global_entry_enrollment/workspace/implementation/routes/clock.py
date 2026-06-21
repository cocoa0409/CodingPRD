"""Test-driving deterministic clock (PRD §2.10).

POST /_clock/set_current_utc — role SchedulingAdmin (scaffold §1.5). The
to_iso8601 field must be a valid ISO 8601 UTC datetime, else ERR_CLOCK_INVALID.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_CLOCK_INVALID
from middleware import require_auth
from response import ok_object
from routes._helpers import get_body, require_fields
from services.lookups import parse_iso_utc

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["SchedulingAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    value = body.get("to_iso8601")
    dt = parse_iso_utc(value)
    if dt is None:
        raise APIError(ERR_CLOCK_INVALID, 422, "to_iso8601 is not a valid ISO 8601 UTC datetime")
    db.clock.set(dt)
    return ok_object(None, 200)
