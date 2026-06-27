"""Logical clock test-driving endpoint (PRD §2.5)."""
from flask import Blueprint

from clock import clock, parse_iso8601
from errors import err
from middleware import get_auth, require_roles
from response import object_response
from validation import get_body, require_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_roles(role, {"BillingAdmin", "ManufacturingOps"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    clock.set(dt)
    return object_response({}, status=200)
