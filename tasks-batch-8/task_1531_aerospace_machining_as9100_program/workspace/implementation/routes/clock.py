"""Logical-clock test-driving endpoint (SystemAdmin only)."""

from flask import Blueprint

from db import db, parse_iso8601
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from validate import json_body, no_unknown

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SystemAdmin")
    data = json_body()
    no_unknown(data, {"to_iso8601"})
    raw = data.get("to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 instant")
    db.set_clock(dt)
    return success_object({"current_utc": raw})
