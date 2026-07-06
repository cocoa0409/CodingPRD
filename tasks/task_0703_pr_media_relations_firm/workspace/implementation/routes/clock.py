"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from clock import clock
from common import get_json_body
from errors import err
from middleware import authorize
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/agency/_clock/set_current_utc")
@authorize(["PlatformAdmin"])
def set_clock():
    body = get_json_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str):
        raise err("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO-8601 string")
    try:
        clock.set(iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be a valid ISO-8601 instant")
    # Output null per endpoint spec; data is an empty object for no-data 2xx.
    return success({}, status=200)
