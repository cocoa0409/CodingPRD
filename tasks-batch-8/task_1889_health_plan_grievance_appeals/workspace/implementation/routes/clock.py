"""Logical server clock endpoints (PRD section 2.4)."""

from flask import Blueprint

import db
import errors
from auth import require_roles
from envelope import success_object
from services import sweep_effectuations_overdue
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.route("/appeals/_clock/set_current_utc", methods=["POST"])
@require_roles({"PlatformAdmin"})
def set_current_utc(_user_id, _role):
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        dt = db.parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    db.clock_set(dt)
    sweep_effectuations_overdue()
    return success_object({"current_utc": db.fmt_ts(db.clock_now())})
