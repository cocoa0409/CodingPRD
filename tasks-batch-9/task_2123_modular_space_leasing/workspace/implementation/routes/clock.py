"""The server's logical clock (PRD 2.6)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import store
from errors import invalid
from guard import auth, get_body, v_string
from response import success

bp = Blueprint("clock", __name__)


def _parse_instant(text):
    candidate = text.strip()
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("FleetAdmin")
    body = get_body()
    raw = v_string(body, "to_iso8601")
    parsed = _parse_instant(raw)
    if parsed is None:
        invalid("'to_iso8601' must be an ISO 8601 instant.")

    store.clock_dt = parsed
    if "T" in raw:
        store.clock_raw = raw
    else:
        store.clock_raw = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return success({"current_utc": store.clock_raw})
