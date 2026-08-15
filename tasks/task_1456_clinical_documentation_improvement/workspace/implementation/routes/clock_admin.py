"""Test-driving endpoint: reset the global logical clock epoch."""
from flask import Blueprint

import clock
from middleware import check_known_fields, get_json_body, require_fields, require_roles
from response import success_object

bp = Blueprint("clock_admin", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"SystemAdmin"})
    body = get_json_body()
    check_known_fields(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    dt = clock.parse_iso8601(body["to_iso8601"], "to_iso8601")
    clock.set_current(dt)
    return success_object({
        "current_utc": clock.to_iso(clock.now()),
        "period_index": clock.period_index(),
    })
