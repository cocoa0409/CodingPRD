"""Logical clock test-driving endpoint (PRD §2.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("NetworkAdmin")
def set_current_utc(_user_id, _role):
    body = get_json_body()
    raw = require_field(body, "to_iso8601")
    dt = parse_iso8601(raw, "to_iso8601")
    db.set_clock(dt)
    return success_object({"current_utc": db.clock_iso()})
