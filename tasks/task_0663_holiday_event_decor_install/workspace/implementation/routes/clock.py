"""Logical clock endpoint (PRD §2.10)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from response import success
from validation import get_json_body, require_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    to_iso8601 = require_datetime(body, "to_iso8601")
    db.clock = to_iso8601
    return success({"current_utc": db.clock})
