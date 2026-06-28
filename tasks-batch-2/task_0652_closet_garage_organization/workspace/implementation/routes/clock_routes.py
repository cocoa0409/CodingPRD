"""Test-driving clock endpoint."""
from flask import Blueprint

from errors import err
from response import object_response
from middleware import get_identity, require_roles
from validate import get_body
from util import parse_iso
from services import clock

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 datetime.")
    clock.set_now(dt)
    return object_response({}, 200)
