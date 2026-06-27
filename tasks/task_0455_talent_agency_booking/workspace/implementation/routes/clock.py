"""Logical clock capability (PRD §2.4)."""
from flask import Blueprint

from db import db, lock
from middleware import get_identity, require_role
from response import object_response
from services.common import get_json_body, require_str
from timeutil import require_dt, normalize_clock_iso

bp = Blueprint("clock", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    body = get_json_body()
    require_str(body, "to_iso8601")
    dt = require_dt(body["to_iso8601"])
    with lock:
        db.clock = normalize_clock_iso(dt)
        now_value = db.clock
    return object_response({"now": now_value}, status=200)
