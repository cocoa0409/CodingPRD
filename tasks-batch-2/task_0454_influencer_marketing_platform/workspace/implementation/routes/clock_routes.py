from flask import Blueprint

from middleware import get_auth, require_role
from validators import get_body, req_str
from clock import clock, parse_iso, format_iso
from errors import err
from response import success

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601", allow_empty=False)
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    return success({"current_utc": format_iso(clock.now())}, status=200)
