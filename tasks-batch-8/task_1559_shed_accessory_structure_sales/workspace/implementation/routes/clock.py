"""Logical clock test-driving endpoint (PRD §2.6)."""

from flask import Blueprint

import db
from errors import invalid_request
from middleware import authenticate, require_roles
from response import success_object
from services.common import get_body, require

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate()
    require_roles("OperationsAdmin")
    body = get_body()
    to_iso8601 = require(body, "to_iso8601", "str")
    try:
        dt = db.parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    current = db.set_clock(db.format_iso(dt))
    return success_object({"current_utc": current})
