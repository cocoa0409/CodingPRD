"""Logical-clock control endpoint (PRD §2.7). Exempt from auth headers."""

from flask import Blueprint, request

from db import store
from errors import err
from response import object_response
from validators import get_body, require

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # This endpoint is exempt from the §2.1 auth headers.
    body = get_body(request)
    to_iso8601 = require(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string")
    try:
        store.set_clock(to_iso8601)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO-8601 instant")
    return object_response({}, 200)
