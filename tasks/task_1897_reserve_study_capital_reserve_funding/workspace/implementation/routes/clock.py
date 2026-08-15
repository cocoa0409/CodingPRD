"""Test-driving clock endpoint."""

from flask import request, Blueprint
from db import store
from middleware import require_roles
from response import success_object
from errors import make_error, ERR_INVALID_REQUEST
from datetime import datetime, timezone

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(force=True, silent=True) or {}

    if "to_iso8601" not in body:
        raise make_error(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")

    iso_str = body["to_iso8601"]
    if not isinstance(iso_str, str):
        raise make_error(ERR_INVALID_REQUEST, "to_iso8601 must be a string")

    # Parse ISO 8601 UTC
    try:
        # Handle both Z and +00:00 suffixes
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise make_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 UTC timestamp")

    store.set_clock(dt)

    return success_object({"current_utc": store.now_iso()})
