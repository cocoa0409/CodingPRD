"""Logical clock endpoint (PRD 2.5): AuditAdmin-only, mounted outside /audit.

Startup default is exactly 2026-08-01T00:00:00Z; before any call the clock reads
that default and never falls back to wall-clock time. The endpoint moves the
clock to the supplied instant and returns the resulting current_utc.
"""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import check_unknown_fields, get_body, req_datetime

bp = Blueprint("clock", __name__)

CLOCK_FIELDS = {"to_iso8601"}


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["AuditAdmin"])
    body = get_body()
    check_unknown_fields(body, CLOCK_FIELDS)
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})
