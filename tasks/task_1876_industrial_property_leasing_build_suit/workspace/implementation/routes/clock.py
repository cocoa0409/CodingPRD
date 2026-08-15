"""Test-driving logical clock (PRD §2.5). Startup default is exactly
2026-08-01T00:00:00Z; this AssetManager-only call moves the clock used by tour
completion, option windows, and option expiry.
"""
from flask import Blueprint

from db import store
from middleware import authenticate, body, require_fields
from response import success_object
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    authenticate(["AssetManager"])
    b = body()
    require_fields(b, [("to_iso8601", "datetime", True)])
    store.clock = parse_iso(b["to_iso8601"])
    return success_object({"current_utc": b["to_iso8601"]})
