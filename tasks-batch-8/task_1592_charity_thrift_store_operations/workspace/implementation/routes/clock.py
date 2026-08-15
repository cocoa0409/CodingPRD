"""Test-driving logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

from db import db, parse_ts, format_ts
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, get_body
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["StoreManager"])
    payload = get_body(required=[("to_iso8601", "string")])
    try:
        dt = parse_ts(payload["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO8601 timestamp")
    db.clock.set(dt)
    return success_object({"current_utc": format_ts(db.clock.now())})
