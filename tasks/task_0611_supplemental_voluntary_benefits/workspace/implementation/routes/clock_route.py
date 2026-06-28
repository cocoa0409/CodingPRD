"""Logical-clock control endpoint (PRD §2.5, scaffold §1.5).

POST /_clock/set_current_utc  (role: System) — advance the server logical clock
to the `to_iso8601` instant. Returns 200 with an empty data object.
"""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601
from middleware import require_roles
from response import success
from validation import get_json_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("System")
def set_clock():
    body = get_json_body()
    value = body.get("to_iso8601")
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("'to_iso8601' is required and must be an ISO 8601 string")
    try:
        instant = parse_iso8601(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("'to_iso8601' must be a valid ISO 8601 datetime")
    clock.set(instant)
    return success({}, 200)
