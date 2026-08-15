"""Test-driving logical clock endpoint."""
from datetime import datetime, timezone

from flask import Blueprint

from db import CLOCK, fmt_clock
from errors import bad_request
from middleware import require_roles
from response import success
from validators import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.post("/leasing/_clock/set_current_utc")
@require_roles("LessorAdmin")
def set_current_utc():
    b = get_body()
    raw = req_str(b, "to_iso8601")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("to_iso8601 must be a valid ISO-8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    CLOCK.set(dt)
    return success({"current_utc": fmt_clock(CLOCK.now())})
