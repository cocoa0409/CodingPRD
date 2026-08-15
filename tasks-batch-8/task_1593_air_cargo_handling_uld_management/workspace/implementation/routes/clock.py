"""Logical clock endpoint (PRD 2.5): the test-driving capability.

Any authenticated role may set the clock by supplying `to_iso8601`; the
response reports the resulting time as `current_utc` (the caller's literal,
echoed verbatim). Before any set call the clock reads exactly
2026-08-01T00:00:00Z; it never falls back to wall-clock time.
"""

from flask import Blueprint

import db
from envelope import success_object
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles, ALL_ROLES
from timeutil import parse_instant
from util import get_json_body, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(*ALL_ROLES)
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    literal = require_field(body, "to_iso8601")
    instant = parse_instant(literal)
    if instant is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    db.set_clock(literal, instant)
    return success_object({"current_utc": db.clock_literal()})
