"""Logical clock control endpoint (FemaAdmin only)."""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601
from middleware import require_roles
from response import success
from helpers import get_body, require_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("FemaAdmin")
def set_clock():
    body = get_body()
    raw = require_str(body, "to_iso8601")
    try:
        instant = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise errors.validation("to_iso8601 must be a valid ISO 8601 instant")
    clock.set(instant)
    # output: null -> empty object data, 200
    return success({}, status=200)
