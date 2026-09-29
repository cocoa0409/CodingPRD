"""The logical clock endpoint (PRD 2.4).  Uniquely, it requires no auth headers."""

from flask import Blueprint

from clock import clock, parse_iso
from response import ok
from validation import bad, body

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body()
    raw = data.get("current_utc")
    if raw is None:
        bad("Field 'current_utc' is required.")
    parsed = parse_iso(raw)
    if parsed is None:
        bad("Field 'current_utc' must be an ISO 8601 UTC timestamp.")
    previous = clock.set(raw, parsed)
    return ok({"current_utc": raw, "previous_utc": previous})
