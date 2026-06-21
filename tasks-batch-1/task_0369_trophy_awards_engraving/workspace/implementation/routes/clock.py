from flask import Blueprint, request
from datetime import datetime, timezone
from db import db
from errors import err
from response import ok
from middleware import KNOWN_ROLES
from services.common import get_json_body, require_fields, is_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Open to Anonymous and ShopManager; auth headers not required.
    role = request.headers.get("X-User-Role")
    if role is not None:
        if role not in KNOWN_ROLES:
            raise err("ERR_UNAUTHENTICATED", "Unknown role")
        if role not in ("Anonymous", "ShopManager"):
            raise err("ERR_FORBIDDEN", "Role not permitted to set the clock")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    value = body["to_iso8601"]
    if not is_str(value):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.clock.set(dt.astimezone(timezone.utc))
    return ok({})
