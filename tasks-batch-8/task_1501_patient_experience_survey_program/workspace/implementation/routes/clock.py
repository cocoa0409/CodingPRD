"""Logical clock control (PRD 2.4). Mounted at the server root, ProgramAdmin
only. The startup default is exactly 2026-08-01T00:00:00Z and never falls
back to the wall clock.
"""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, reject_unknown_fields, require_string, parse_iso8601

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ProgramAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"to_iso8601"})
    value = require_string(body, "to_iso8601")
    parse_iso8601(value, "to_iso8601")  # validates; the verbatim string is stored
    db.set_clock_raw(value)
    return success_object({"current_utc": db.clock_now()})
