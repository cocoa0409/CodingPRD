"""Test-driving logical clock: POST /midway/_clock/set_current_utc.

Startup default is exactly 2026-08-01T00:00:00Z; the clock never falls back to
wall-clock time and is never rewound below the startup default.
"""
from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import authenticate
from response import ok
from validators import get_body, reject_unknown, req_str

bp = Blueprint("clock", __name__)


def _parse_iso8601(raw):
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["StateProgramAdmin"])
    body = get_body()
    reject_unknown(body, {"to_iso8601"})
    raw = req_str(body, "to_iso8601")
    target = _parse_iso8601(raw)
    if target < db.CLOCK_START:
        raise_err(ERR_INVALID_REQUEST, "The logical clock is never rewound below the startup default")
    db.clock_set(target)
    return ok({"current_utc": db.now_iso()})
