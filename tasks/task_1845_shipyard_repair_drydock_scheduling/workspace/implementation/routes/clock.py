"""Logical clock endpoint (test-driving capability, PRD 2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services import project_ops
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
@require_roles("YardAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_current_utc(to_iso8601)
    # Each advance sweeps permit expiry and warranty closure.
    project_ops.run_clock_sweeps(new_dt)
    return success_object({"current_utc": db.get_current_utc()})
