"""Logical clock endpoints."""

from flask import Blueprint

from middleware import require_roles
from response import success_object
from services.cascade import advance_clock, clock_now_iso
from util import require_body, get_string, parse_datetime, reject_unexpected

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {"to_iso8601"})
    to_s = get_string(body, "to_iso8601")
    to_dt = parse_datetime(to_s, "to_iso8601")
    advance_clock(to_dt)
    return success_object({"current_utc": clock_now_iso()})
