"""Logical clock test-driving endpoint (PRD section 2.9)."""
from flask import Blueprint

import db
from errors import err_invalid_request
from middleware import require_roles
from response import success
from routes.common import body_json
from services.timeutil import fmt_ts, parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/ltl/_clock/set_current_utc", methods=["POST"])
@require_roles("TerminalAdmin")
def set_current_utc():
    body = body_json()
    raw = body.get("to_iso8601")
    if raw is None:
        raise err_invalid_request("to_iso8601 is required")
    try:
        dt = parse_iso(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be an ISO 8601 instant")
    db.set_clock(dt)
    return success({"current_utc": fmt_ts(db.now())})
