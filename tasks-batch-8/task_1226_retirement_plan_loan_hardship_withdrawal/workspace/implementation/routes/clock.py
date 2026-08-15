"""Test-driving logical clock endpoint."""

from flask import Blueprint, request

import errors
from clock import CLOCK, format_date_iso, _parse_iso
from middleware import require_roles
from response import success_object
from services.state import clock_advance

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("RecordkeeperAdmin")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object", 400)
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "to_iso8601 is required and must be an ISO 8601 string", 400)
    try:
        target = _parse_iso(to_iso8601)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "to_iso8601 must be a valid ISO 8601 timestamp", 400)
    CLOCK.set(to_iso8601)
    clock_advance(target)
    return success_object({"current_utc": format_date_iso(CLOCK.now())})
