"""Logical clock test-driving endpoint."""
from flask import Blueprint

import store
import core as c

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Exempt from authentication per validation rules (test-driving utility).
    body = c.get_body()
    target = c.require_str(body, "to_iso8601")
    dt = store._parse_instant(target)
    store.clock.set(dt)
    return c.ok({"current_utc": store.fmt_ts(dt)})
