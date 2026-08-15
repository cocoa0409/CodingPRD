from flask import Blueprint, request

from db import store
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.lifecycle import sweep
from timeutil import parse_instant, format_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 required")
    try:
        dt = parse_instant(to_iso)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 malformed")
    store.clock_iso = format_instant(dt)
    transitions = sweep()
    return success_object({
        "current_utc": store.clock_iso,
        "transitions_applied": transitions,
    })
