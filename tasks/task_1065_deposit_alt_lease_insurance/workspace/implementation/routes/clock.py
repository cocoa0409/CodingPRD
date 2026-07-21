from flask import Blueprint
from db import set_logical_clock
from middleware import get_caller, require_role
from response import object_response
from validate import body, require_datetime

clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    require_role(caller, {"PlatformAdmin"})
    b = body()
    to_dt = require_datetime(b, "to_iso8601")
    set_logical_clock(to_dt)
    return object_response({}, 200)
