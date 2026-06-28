"""Logical-clock control endpoint (PRD §2.8)."""
from flask import Blueprint

import db
import response
from middleware import require_auth, get_json_body, parse_iso8601
from services import validators

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth({"Registrar"})
    body = get_json_body()
    to_iso = validators.require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso, "to_iso8601")
    db.set_clock(dt)
    # Output is null (no resource), returned as an empty object in data.
    return response.success({}, 200)
