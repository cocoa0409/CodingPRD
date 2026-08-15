"""Logical clock endpoint (PRD 2.8)."""
from datetime import timezone

from flask import Blueprint

from db import store
from errors import invalid_request
from middleware import auth
from response import ok
from services.workflow import parse_dt
from validators import body, req_str

bp = Blueprint("clock", __name__)


def _format_utc(dt):
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        frac = f"{dt.microsecond:06d}".rstrip("0")
        return f"{base}.{frac}Z"
    return f"{base}Z"


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["Underwriter"])
    data = body()
    raw = req_str(data, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.logical_clock = dt.astimezone(timezone.utc)
    return ok({"current_utc": _format_utc(store.logical_clock)})
