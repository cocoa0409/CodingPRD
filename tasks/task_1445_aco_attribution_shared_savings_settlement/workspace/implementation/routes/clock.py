"""Test-driving logical clock (PlatformAdmin only).

Startup default is exactly 2026-08-01T00:00:00Z and never falls back to
wall-clock time.
"""
from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import bad_request
from middleware import require_roles, ROLE_PLATFORM
from response import success
from validate import get_json_body, validate_body

bp = Blueprint("clock", __name__)

CLOCK_SPEC = {
    "to_iso8601": {"type": "string", "required": True},
}


def parse_iso8601(value):
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("to_iso8601 must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@bp.post("/aco/_clock/set_current_utc")
def set_current_utc():
    require_roles([ROLE_PLATFORM])
    body = validate_body(get_json_body(), CLOCK_SPEC)
    db.set_logical_now(parse_iso8601(body["to_iso8601"]))
    return success({"current_utc": db.render_logical(db.logical_now())})
