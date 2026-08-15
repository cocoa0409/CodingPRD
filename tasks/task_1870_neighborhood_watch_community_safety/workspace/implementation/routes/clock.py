"""POST /watch/_clock/set_current_utc"""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/watch/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("ProgramCoordinator")
    body = request.get_json(force=True, silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601:
        raise errors.invalid_request("to_iso8601 is required")
    try:
        dt = db.parse_iso(to_iso8601)
    except Exception:
        raise errors.invalid_request("to_iso8601 is not a valid ISO-8601 timestamp")
    db.set_clock(dt)
    return success_object({"current_utc": db.to_iso(dt)}, 200)
