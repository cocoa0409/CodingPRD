"""PRD 2.4 -- the logical clock. Startup reads exactly 2026-08-01T00:00:00Z."""

from flask import Blueprint

import validation as V
from middleware import roles_required
from response import object_response
from store import fmt_dt, set_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@roles_required("PlatformAdmin")
def set_current_utc():
    data = V.body()
    target = V.parse_datetime(data.get("to_iso8601"), "to_iso8601")
    current = set_clock(target)
    return object_response({"current_utc": fmt_dt(current)})
