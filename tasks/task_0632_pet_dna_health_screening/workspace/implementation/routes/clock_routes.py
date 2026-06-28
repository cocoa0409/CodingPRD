"""Logical clock setter (PRD §2.4)."""
from flask import Blueprint

from clock import clock, parse_iso8601
from errors import err, ERR_INVALID_REQUEST
from helpers import get_json_body, require_fields
from middleware import require_roles
from response import success

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/dna/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles({"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_iso8601(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    # output: null -> empty data object
    return success({}, status=200)
