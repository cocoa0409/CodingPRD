"""POST /_clock/set_current_utc — logical clock (PRD §2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services.deaccession import sweep_cooling_off
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_clock(to_iso8601, new_dt)
    sweep_cooling_off()
    return success_object({"current_utc": db.get_clock_raw()})
