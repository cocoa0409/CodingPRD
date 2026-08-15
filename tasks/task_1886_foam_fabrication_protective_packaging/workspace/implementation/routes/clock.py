"""Logical clock test-driving endpoint (PlatformAdmin only, PRD §2.4)."""
from flask import Blueprint

import db
from middleware import get_auth_context, require_role
from response import success_object
from services.common import body, parse_iso_datetime, req_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = get_auth_context()
    require_role(role, ("PlatformAdmin",))
    data = body()
    raw = req_str(data, "to_iso8601")
    parse_iso_datetime(raw, "to_iso8601")
    db.set_clock(raw)
    return success_object({"current_utc": db.clock_raw()})
