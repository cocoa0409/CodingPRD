"""Logical clock (PRD 2.4): Owner-only test-driving endpoint."""
from flask import Blueprint

from authz import require_role
from db import store
from errors import malformed
from helpers import body, req_field
from respond import success
from timeutil import fmt_dt, parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    require_role("Owner")
    data = body()
    raw = req_field(data, "to_iso8601")
    try:
        instant = parse_datetime(raw)
    except ValueError:
        raise malformed("to_iso8601 must be an ISO 8601 datetime")
    store.clock = instant
    return success({"current_utc": fmt_dt(store.clock)})
