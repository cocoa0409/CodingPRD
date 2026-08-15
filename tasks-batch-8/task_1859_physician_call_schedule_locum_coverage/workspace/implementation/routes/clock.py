"""Test-driving logical clock (PRD §2.5): SchedulerAdmin-only. The clock starts
at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time."""
from flask import Blueprint

import db
import validation as V
from middleware import require_roles
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(["SchedulerAdmin"])
    body = V.json_body()
    dt = V.parse_iso8601(body.get("to_iso8601"), "to_iso8601")
    db.set_logical(dt)
    return ok({"current_utc": db.iso_logical(db.now_logical())})
