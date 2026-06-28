"""Logical clock driver (PRD 3.13). OpsAdmin only."""

from flask import Blueprint

from clock import clock
from common import get_json_body, parse_iso8601, require_fields
from errors import err
from middleware import get_auth, require_role
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"])
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    clock.set(dt)
    return success({}, status=200)
