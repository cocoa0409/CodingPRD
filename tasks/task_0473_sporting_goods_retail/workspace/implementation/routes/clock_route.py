"""Logical-clock route: POST /_clock/set_current_utc (PRD §2.7)."""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601
from helpers import get_body, as_str
from middleware import require_roles
from response import success

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    to_iso8601 = as_str(body, "to_iso8601", required=True)
    try:
        instant = parse_iso8601(to_iso8601)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    clock.set(instant)
    # Clock-set returns 200 with an empty data object (PRD §4, output: null).
    return success({}, 200)
