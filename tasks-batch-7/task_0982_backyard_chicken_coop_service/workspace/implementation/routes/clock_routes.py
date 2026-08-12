"""Logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

from db import store
from middleware import authenticate, body, require_role
from response import ok
from util import fmt_ts, parse_dt
from errors import fail

bp = Blueprint("clock", __name__)


@bp.route("/coopcare/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate_role = authenticate()
    require_role(authenticate_role[1], {"PlatformAdmin"})
    data = body()
    target = parse_dt(data.get("to_iso8601"))
    if target is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    store.clock = target
    return ok({"current_utc": fmt_ts(store.clock)}, 200)
