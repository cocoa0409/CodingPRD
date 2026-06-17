"""YardClock test-driving endpoints (PRD §2.7)."""
from flask import Blueprint

import errors
from db import DB, LOCK, ensure_clock
from middleware import require_auth
from services.common import require_body, req_datetime, serialize, parse_datetime
from response import object_response
from .helpers import get_json_body

bp = Blueprint("clock", __name__)


def _clock_view():
    """YardClock carries only id/created_at/current_utc (PRD §2.4 singleton)."""
    clk = ensure_clock()
    return serialize(clk)


@bp.post("/rental-yard/_clock/set_current_utc")
def set_clock():
    require_auth({"YardManager"})
    body = require_body(get_json_body())
    to_iso = req_datetime(body, "to_iso8601")
    with LOCK:
        clk = ensure_clock()
        # Normalize to ISO 8601 UTC with three fractional digits for storage so
        # downstream date comparisons read a consistent format (PRD §2.7).
        dt = parse_datetime(to_iso)
        clk["current_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return object_response(_clock_view(), 200)


@bp.get("/rental-yard/_clock")
def get_clock():
    return object_response(_clock_view(), 200)
