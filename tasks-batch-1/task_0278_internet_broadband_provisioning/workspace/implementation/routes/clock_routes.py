"""Test-driving clock endpoint (PRD §3.12)."""
from flask import Blueprint

from clock import get_clock
from errors import err
from middleware import get_user_context, require_role
from response import object_response
from services.helpers import get_json_body, require_fields
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = get_user_context()
    require_role(role, {"NetworkOps", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp.")
    get_clock().set_now(dt)
    return object_response({}, 200)
