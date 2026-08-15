"""Logical clock endpoint."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role({"QualityManager"})
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601 or not isinstance(to_iso8601, str):
        raise errors.invalid_request("to_iso8601 required")
    # Validate it parses
    from services.common import parse_iso
    parse_iso(to_iso8601)
    db.set_clock(to_iso8601)
    return success_object({"current_utc": db.get_clock()})
