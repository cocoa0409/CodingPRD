"""Server clock test-driving endpoint (PRD §2.6)."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success
from services.common import get_json_body, require_fields, parse_iso

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PropertyManager")
def set_clock():
    body = get_json_body()
    require_fields(body, "to_iso8601")
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    return success({}, status=200)
