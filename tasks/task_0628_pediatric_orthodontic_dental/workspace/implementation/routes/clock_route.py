"""Logical clock endpoint (PRD §2.4)."""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601
from db import lock
from helpers import get_json_body, require_fields
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ClinicAdmin")
def set_clock():
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        instant = parse_iso8601(body["to_iso8601"])
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    with lock:
        clock.set(instant)
    return success({}, 200)
