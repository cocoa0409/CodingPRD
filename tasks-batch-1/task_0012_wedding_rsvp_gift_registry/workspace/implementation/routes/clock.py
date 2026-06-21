"""Test-driving clock endpoint (scaffold §1.5)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str) or not iso:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
    # Validate parse.
    try:
        db.parse_iso(iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO-8601 string")
    db.set_current_utc(iso)
    return ok_object({"current_utc": iso})
