"""Logical clock endpoint (test-driving) with the NOC overdue sweep."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.domain import noc_overdue_sweep
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/ach/_clock/set_current_utc", methods=["POST"])
@require_roles(*ALL_ROLES)
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_clock(new_dt)
    noc_overdue_sweep()
    return success_object({"current_utc": db.clock_iso()})
