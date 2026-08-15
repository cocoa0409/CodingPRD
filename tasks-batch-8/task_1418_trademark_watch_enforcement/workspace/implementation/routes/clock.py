"""Logical clock endpoint (PRD 2.5) — PlatformAdmin-only test driver."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success
from services.domain import run_sweep
from util import get_payload, reject_unknown_fields, require_datetime, fmt_business

bp = Blueprint("clock", __name__)


@bp.route("/brand/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = require_roles("PlatformAdmin")
    body = get_payload()
    reject_unknown_fields(body, {"to_iso8601"})
    target = require_datetime(body, "to_iso8601")
    db.clock.set(target)
    # Every clock set runs the full time-based sweep at the new instant.
    run_sweep(db.clock.now())
    return success({"current_utc": fmt_business(db.clock.now())}, 200)
