"""Logical clock test-driving endpoint."""
from flask import Blueprint
from db import db
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles
from response import success
from services.helpers import body, require_fields, require_str

bp = Blueprint("clock", __name__)


@bp.route("/supply/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("CreditManager")
    b = body()
    require_fields(b, "to_iso8601")
    to_iso = require_str(b, "to_iso8601")
    try:
        db.clock.set(to_iso)
    except Exception:
        raise ApiError(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 timestamp", 400)
    return success({"current_utc": db.clock.iso()})
