from flask import Blueprint

from common import authenticate, require_role, body_json, require_present, parse_iso, respond
from store import db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    value = require_present(body, "to_iso8601")
    if not isinstance(value, str):
        from errors import ApiError
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO8601 string")
    db.clock = parse_iso(value)
    return respond({}, "object", 200)
