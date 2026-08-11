"""Logical clock endpoint (test-driving). Startup default 2026-05-01T00:00:00Z."""
from datetime import datetime, timezone

from flask import Blueprint

from db import clock_now, fmt_ts, set_clock
from errors import ERR_INVALID_REQUEST, raise_err
from middleware import authenticate, require_roles
from response import success
from validation import body, req_str

bp = Blueprint("clock", __name__)


@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = authenticate()
    require_roles(caller, ["ContractorAdmin"])
    data = body()
    raw = req_str(data, "to_iso8601")
    dt = None
    try:
        if len(raw) == 10:
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = None
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "Field 'to_iso8601' must be a valid ISO 8601 instant")
    set_clock(dt)
    return success({"current_utc": fmt_ts(clock_now())}, code=200)
