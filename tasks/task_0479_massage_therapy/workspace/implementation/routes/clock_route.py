"""Logical clock control (PRD §2.5). Note: NOT under the /practice prefix."""
from flask import Blueprint

import clock
import helpers as h
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()
    to_iso = util.parse_iso(h.require(body, "to_iso8601"))
    clock.set_now(to_iso)
    return response.success({"now": util.iso_format(to_iso)})
