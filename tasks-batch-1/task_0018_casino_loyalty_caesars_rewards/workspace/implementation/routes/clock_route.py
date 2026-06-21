"""POST /_clock/set_current_utc — test-driving capability per PRD §2.11."""
from flask import Blueprint

import clock
from auth import require_role
from common import get_json_or_400, require_iso_datetime
from response import success_object


bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role({"ComplianceOfficer"})
    body = get_json_or_400()
    dt = require_iso_datetime(body, "to_iso8601")
    clock.set_clock(dt)
    return success_object({"current_utc": clock.iso(clock.now())}, 200)
