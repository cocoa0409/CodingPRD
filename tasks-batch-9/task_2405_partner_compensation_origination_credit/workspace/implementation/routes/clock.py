"""Test-only logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

from db import iso, store
from middleware import authorize
from response import raw_ok
from validation import bad, get_body, parse_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(["CycleAdmin"])
    body = get_body()
    if "to_iso8601" not in body:
        bad()
    store.clock = parse_instant(body["to_iso8601"])
    return raw_ok({"current_utc": iso(store.clock)})
