"""Logical clock endpoint (PRD 2.5)."""

from flask import Blueprint

import util
import clock
from middleware import require_roles
from response import success_object
from services import core

bp = Blueprint("clock_routes", __name__)


@bp.post("/vfd/_clock/set_current_utc")
def set_current_utc():
    require_roles("Inspector")
    body = util.get_json_body()
    to_iso8601 = util.require_field(body, "to_iso8601")
    dt = util.parse_iso(to_iso8601, "to_iso8601")
    clock.set_now(dt)
    core.apply_clock_cascades()
    return success_object({"now_utc": util.iso_from_dt(clock.now())})
