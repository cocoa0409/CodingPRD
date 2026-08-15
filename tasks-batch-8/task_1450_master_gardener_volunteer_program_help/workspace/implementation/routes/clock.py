"""Logical clock test-driving endpoint."""

from flask import request, Blueprint

import db
import util
from middleware import auth_context
from errors import raise_err
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth_context(["ProgramCoordinator"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    to_iso = body.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str) or not util.is_iso_datetime(to_iso):
        raise_err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    # Normalize to UTC Z form
    dt = util.parse_dt(to_iso)
    db.clock_state["current_utc"] = util._format_dt(dt)
    return success_object({"current_utc": db.clock_state["current_utc"]})
