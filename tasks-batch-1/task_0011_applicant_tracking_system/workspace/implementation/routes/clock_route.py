"""Test-driving clock endpoint."""
from flask import Blueprint, jsonify

import clock
from common import get_json_or_400, require_str
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_object
from services.cascades import sweep_offer_expiry


bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # No authentication required per PRD §2.1 + §3.8.
    body = get_json_or_400()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = clock.parse_iso(to_iso)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 invalid")
    clock.set_clock(dt)
    revoked = sweep_offer_expiry()
    return success_object({"now": clock.iso(clock.now()), "revoked_offer_ids": revoked}, status=200)
