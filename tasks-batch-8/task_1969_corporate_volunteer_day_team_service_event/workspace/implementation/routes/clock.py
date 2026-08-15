"""Logical clock test-driving endpoint (PlatformAdmin only)."""
from flask import Blueprint

from db import db
from middleware import authenticate, body
from response import success_object
from timeutil import fmt_ts, parse_datetime
from validate import req_present

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    data = body()
    raw = req_present(data, "to_iso8601")
    dt = parse_datetime(raw, "to_iso8601")
    db.set_clock(dt)
    return success_object({"current_utc": fmt_ts(db.now())})
