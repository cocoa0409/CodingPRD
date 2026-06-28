"""Test-driving logical clock endpoint (PRD §2.9)."""
from flask import Blueprint

import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success
from clock import clock

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    body = get_body()
    to_iso = helpers.require_str(body, "to_iso8601")
    dt = helpers.parse_iso8601(to_iso)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 instant.")
    clock.set(dt)
    return success({}, status=200)
