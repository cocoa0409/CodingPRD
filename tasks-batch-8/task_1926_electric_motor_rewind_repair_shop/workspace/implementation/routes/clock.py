"""Test-driving logical clock."""
from flask import Blueprint
from middleware import require_role
from errors import err_invalid_input
from db import store, parse_iso, format_ts
from response import success_object
from routes.common import get_json_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("ShopAdmin")
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err_invalid_input("to_iso8601 must be an ISO 8601 string")
    try:
        dt = parse_iso(to_iso)
    except Exception:
        raise err_invalid_input("to_iso8601 is not a valid ISO 8601 timestamp")
    store.set_clock(dt)
    return success_object({"current_utc": format_ts(store.now())})
