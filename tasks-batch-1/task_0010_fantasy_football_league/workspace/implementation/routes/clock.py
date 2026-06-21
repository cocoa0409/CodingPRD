"""Test-driving clock endpoint."""
from flask import Blueprint, request

from db import set_clock
from errors import err_invalid_request
from middleware import require_role
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("Commissioner")
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise err_invalid_request("to_iso8601 required (ISO 8601 string).")
    try:
        normalized = set_clock(to_iso8601)
    except Exception:
        raise err_invalid_request("to_iso8601 not parseable.")
    return success_object({"current_utc": normalized})
