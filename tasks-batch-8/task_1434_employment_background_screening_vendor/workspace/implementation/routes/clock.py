"""POST /_clock/set_current_utc — test-driving logical clock."""
from flask import Blueprint

import timeutil
from middleware import auth, require_role, get_body, req_str, invalid
from response import success_object
from timeutil import parse_iso, fmt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_uid, role = auth()
    require_role(role, {"HRAdmin", "ComplianceOfficer"})
    body = get_body()
    raw = req_str(body, "to_iso8601")
    try:
        dt = parse_iso(raw)
    except (ValueError, TypeError):
        invalid("to_iso8601 must be a valid ISO 8601 instant")
    timeutil.CLOCK.set(dt)
    return success_object({"current_utc": fmt(timeutil.CLOCK.now())}, 200)
