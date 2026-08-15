"""Test-driving logical clock endpoint."""
from flask import Blueprint

from errors import ERR_CLOCK_REGRESSION, ERR_INVALID_REQUEST, raise_err
from middleware import user_context, require_role
from response import ok_object
from services.core import body, run_sweep
from util import CLOCK, fmt_ts, parse_ts

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    data = body()
    raw = data.get("to_iso8601")
    try:
        target = parse_ts(raw)
    except (ValueError, TypeError, AttributeError):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp string")

    user_id, role = user_context()
    require_role(role, {"PlatformAdmin"})

    if target < CLOCK.now():
        raise_err(ERR_CLOCK_REGRESSION, "to_iso8601 is earlier than the current logical clock")

    CLOCK.set(target)
    run_sweep()
    return ok_object({"current_utc": fmt_ts(CLOCK.now())})
