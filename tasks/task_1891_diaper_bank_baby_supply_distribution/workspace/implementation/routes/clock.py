"""Logical clock test-driving endpoint (PRD §2.4)."""

from db import store, fmt_ts
from middleware import authenticate, require_role
from response import success_object, get_body
from validate import parse_datetime
from . import make_blueprint

bp = make_blueprint("clock")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, ["BankAdmin"])
    body = get_body()
    target = parse_datetime(body.get("to_iso8601"), "to_iso8601")
    store.clock = target
    return success_object({"current_utc": fmt_ts(store.clock)})
