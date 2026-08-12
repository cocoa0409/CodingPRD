"""Test-driving logical clock endpoint (Court only)."""
from flask import Blueprint

from logical_clock import CLOCK
from middleware import auth_context, require_roles, json_body
from response import ok_object
from util import parse_datetime

bp = Blueprint("clock", __name__)


@bp.route("/trustee/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth_context()
    require_roles(role, ("Court",))
    body = json_body()
    to = parse_datetime(body.get("to_iso8601"), "to_iso8601")
    CLOCK.set(to)
    return ok_object({}, status=200)
