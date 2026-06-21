"""Logical-clock control endpoint (PRD §3.6 / endpoint §1.5).

This endpoint is the one exception to the §2.1 auth-header rule: it still
requires the PlatformAdmin role, but the validation order puts the role gate
first (an unknown/missing role is an auth failure, a known-but-wrong role is a
forbidden-role failure).
"""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_role
from response import object_response
from validators import get_body, require

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_body(request)
    to_iso8601 = require(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string")
    try:
        store.set_clock(to_iso8601)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO-8601 instant")
    from db import iso_millis
    return object_response({"current_utc": iso_millis(store.now())}, 200)
