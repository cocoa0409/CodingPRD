"""Test-driving clock endpoint."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_fields, require_string


bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(["LabDirector"])()
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    require_string(iso, "to_iso8601")
    try:
        state = db.set_current_utc(iso)
    except Exception as e:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Invalid ISO 8601 timestamp: {e}")
    # Scaffold says output: null. Return the new state for observability.
    return ok_object(state)
