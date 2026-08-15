"""Logical clock endpoint."""
from flask import Blueprint, request

from db import db
from middleware import require_role
from response import success_object
from utils import now_stamp

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso:
        from errors import ERR_INVALID_REQUEST, ApiError
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required.", 400)
    # Normalise: accept any ISO8601 instant
    raw = str(to_iso).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        from errors import ERR_INVALID_REQUEST, ApiError
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO8601 instant.", 400)
    # Store back with Z suffix
    db.clock = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success_object({"current_utc": db.clock})
