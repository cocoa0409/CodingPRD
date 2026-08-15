"""POST /_clock/set_current_utc — logical clock test-driving endpoint."""

from flask import Blueprint

import db
from errors import fail
from helpers import get_json_body, require_str
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ShowDirector")
    body = get_json_body()
    raw = require_str(body, "to_iso8601")
    try:
        dt = db._parse_iso(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO-8601 instant")
    db.clock.set(dt)
    return success_object({"current_utc": db._fmt_iso(dt)}, 200)
