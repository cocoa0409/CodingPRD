"""POST /api/_clock/set_current_utc — logical clock control (Controller only)."""
from flask import Blueprint, request
from middleware import get_user_context, require_roles
from response import success_object
from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
from clock import clock, parse_iso, format_iso

bp = Blueprint("clock_routes", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    body = request.get_json(force=True, silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "to_iso8601 is required and must be an ISO8601 UTC string",
            400,
        )
    try:
        dt = parse_iso(to_iso8601)
    except Exception:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "to_iso8601 must be a valid ISO8601 UTC instant",
            400,
        )
    clock.set(dt)
    return success_object({"now_iso8601": format_iso(clock.now())}, 200)
