"""Logical clock endpoint (PRD 2.8)."""
from flask import Blueprint

from clock import clock
from middleware import get_auth, require_role
from response import object_response
from util import get_json_body, require_fields, parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/pers/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # PRD 2.1: clock endpoint still requires both auth headers.
    _user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    clock.set(dt)
    # PRD: output null -> empty object in data
    return object_response({}, 200)
