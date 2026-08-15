"""Logical clock endpoint (SystemAdmin only)."""
from flask import Blueprint

import clock
import response
from auth import require_roles
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdmin")
def set_clock(user_id, role):
    body = get_body()
    to = clock.parse_dt(body.get("to_iso8601"))
    clock.set_current(to)
    return response.success({"current_utc": clock.iso(clock.now())}, 200)
