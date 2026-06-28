from flask import Blueprint

from db import store
from middleware import authenticate, require_roles
from common import get_json_body, require_string
from clock import set_clock
from response import success

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    body = get_json_body()
    to_iso8601 = require_string(body, "to_iso8601")
    with store.lock:
        set_clock(to_iso8601)
        return success({})
