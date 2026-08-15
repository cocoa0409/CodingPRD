"""Logical clock test-driving capability (PRD §2.4). The single endpoint
mounted outside the /api prefix."""
from flask import Blueprint

import db
from middleware import ROLE_MANAGER, require_roles
from response import success_object
from validation import json_body, req_datetime_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(ROLE_MANAGER)
    body = json_body()
    to_iso8601 = req_datetime_str(body, "to_iso8601")
    db.set_clock(db.parse_dt(to_iso8601))
    return success_object({"current_utc": db.fmt_dt(db.now())})
