"""Test-driving logical clock (PRD §2.4)."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    require_datetime(body, "to_iso8601")
    db.set_current_utc(body["to_iso8601"])
    # Output is null per the endpoint table; data becomes {} in the envelope.
    return ok_object(None, 200)
