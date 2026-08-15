"""Test-driving logical clock endpoint."""
from flask import Blueprint

import db
from db import format_ts
from helpers import body_json, parse_iso8601
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = require_roles({"ShopManager"})
    data = body_json()
    to_iso8601 = data.get("to_iso8601")
    dt = parse_iso8601(to_iso8601, field="to_iso8601")
    db.set_clock(dt)
    # Response carries the resulting current_utc. Use the canonical ISO form.
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        ms = dt.microsecond // 1000
        iso += ".%03d" % ms
    iso += "Z"
    return success_object({"current_utc": iso})
