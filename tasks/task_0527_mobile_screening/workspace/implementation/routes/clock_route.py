from flask import Blueprint
from clock import clock, parse_iso
from middleware import require_user_context, require_role
from response import object_response
from services.common import get_json_body
from errors import err

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str) or not iso:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 string")
    try:
        parse_iso(iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not valid ISO8601")
    clock.set(iso)
    return object_response({"current_utc": clock.now_iso()}, 200)
