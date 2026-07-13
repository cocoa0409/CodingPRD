"""Logical clock administration route."""
from flask import Blueprint
from store import store
from auth import require_role, body
from errors import err
from envelope import success
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role({"Registrar"})
    data = body()
    if data.get("to_iso8601") is None:
        raise err("ERR_VALIDATION", "Missing required field: to_iso8601")
    dt = parse_iso(data["to_iso8601"])
    if dt is None:
        raise err("ERR_VALIDATION", "to_iso8601 must be a valid ISO-8601 timestamp")
    store.clock = dt
    return success({}, status=200)
