"""Test-driving logical clock endpoint."""
from flask import Blueprint

import db
from middleware import require_roles, get_json_body, require_field
from response import success_object
from util import parse_datetime, fmt_clock
from errors import err_invalid_request

bp = Blueprint("clock", __name__)

PREFIX = "/packaging-distribution"


@bp.route(f"{PREFIX}/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_json_body(required=True)
    raw = require_field(body, "to_iso8601")
    if not isinstance(raw, str):
        raise err_invalid_request("Field 'to_iso8601' must be an ISO 8601 datetime string.")
    dt = parse_datetime(raw, "to_iso8601")
    db.set_clock(dt)
    return success_object({"current_utc": fmt_clock(db.now())})
