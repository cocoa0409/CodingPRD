from flask import Blueprint

from clock import clock, parse_iso, to_iso
from middleware import auth, require_role
from errors import err, ERR_INVALID_REQUEST
from helpers import body, require_str
from response import ok_object

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require_role(role, {"PlatformAdmin"})
    data = body()
    to_iso8601 = require_str(data, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "Invalid to_iso8601")
    clock.set(dt)
    return ok_object({"current_utc": to_iso(clock.now())})
