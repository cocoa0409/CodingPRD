"""Logical clock test-driving endpoint."""

from flask import Blueprint, request

from db import db
from errors import validation
from middleware import require_roles
from response import success_object
from services.core import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("SystemAdmin")
    body = request.get_json(silent=True) or {}
    if "to_iso8601" not in body:
        raise validation("to_iso8601 is required")
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    db.logical_clock = dt
    out = {
        "current_utc": dt.strftime("%Y-%m-%dT%H:%M:%S.") +
                       f"{dt.microsecond // 1000:03d}Z"
    }
    return success_object(out)
