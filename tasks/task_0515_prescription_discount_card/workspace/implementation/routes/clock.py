"""Test-driving logical clock (PRD §2.9). No auth required."""
from flask import Blueprint
import db
import response
import common
import errors

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Public / auth-exempt per PRD §2.1.
    body = common.get_body()
    to_iso = common.req_str(body, "to_iso8601")
    if db.parse_iso(to_iso) is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant.")
    db.set_clock(to_iso)
    return response.object_response({}, 200)
