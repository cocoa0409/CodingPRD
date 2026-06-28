"""Test-driving logical clock endpoint (PRD §3.11)."""
from flask import Blueprint

from db import db
from helpers import get_body, require_str, parse_iso8601
from middleware import require_roles
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("AccountAdmin")
def set_clock():
    body = get_body()
    to_iso8601 = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_clock(dt)
    # output: null -> data is an empty object for a 2xx with no resource.
    return object_response({})
