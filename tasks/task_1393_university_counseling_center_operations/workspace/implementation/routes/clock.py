"""Logical clock endpoint (test-driving)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services.domain import apply_clock_transitions
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/ucc/_clock/set_current_utc", methods=["POST"])
@require_roles("ClinicalDirector")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_clock(new_dt)
    apply_clock_transitions(new_dt)
    return success_object({"current_utc": db.clock_iso()})
