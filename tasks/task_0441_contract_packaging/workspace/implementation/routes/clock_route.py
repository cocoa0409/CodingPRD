"""Logical clock control endpoint (PRD §2.11)."""
from flask import Blueprint

import clock
import errors
import response
import util
from middleware import require_role, ALL_ROLES

bp = Blueprint("clock", __name__)


@bp.route("/copack/_clock/set_current_utc", methods=["POST"])
@require_role(*ALL_ROLES)
def set_clock():
    body = util.get_json_body()
    util.require_fields(body, "to_iso8601")
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise errors.invalid_request("to_iso8601 must be a string")
    parsed = clock.parse_iso8601(to_iso)
    if parsed is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    clock.set_now(parsed)
    return response.success({"current_utc": clock.to_iso_millis(parsed)}, status=200)
