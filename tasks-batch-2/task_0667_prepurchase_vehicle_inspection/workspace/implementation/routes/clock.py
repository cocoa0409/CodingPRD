"""Logical clock control endpoint (PRD §2.4)."""
from flask import Blueprint

from clock import clock
from helpers import get_json_body, parse_iso8601, require_fields
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("OpsAdmin")
def set_clock():
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"], "to_iso8601")
    clock.set(dt)
    return success({}, status=200)
