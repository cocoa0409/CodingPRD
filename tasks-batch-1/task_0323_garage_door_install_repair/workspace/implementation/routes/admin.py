"""Test-driving clock endpoint (PRD §3.13)."""
from flask import Blueprint

import clock
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["to_iso8601"])
    dt = util.parse_dt(body.get("to_iso8601"), "to_iso8601")
    clock.set_now(dt)
    return success({})
