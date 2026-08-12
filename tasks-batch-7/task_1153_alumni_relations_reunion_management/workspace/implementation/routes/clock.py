"""Test-driving logical clock endpoint."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services.common import format_ts, json_body, parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/alumni/_clock/set_current_utc", methods=["POST"])
@require_roles("AlumniRelationsStaff", "AlumniRelationsDirector")
def set_current_utc(_role, _user_id):
    body = json_body(required=["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    db.LogicalClock.set(dt)
    return success_object({"current_utc": format_ts(db.logical_now())})
