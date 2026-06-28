from flask import Blueprint

from clock import clock
from db import iso_now_ms
from middleware import authenticate, require_roles
from response import success_object
from services.common import get_json_body, require_str, parse_iso

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    clock.set(dt)
    return success_object({"now": iso_now_ms(dt)})
