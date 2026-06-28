"""Test-driving logical clock endpoint (PRD 2.5 / 4)."""
from flask import Blueprint

from clock import clock
from errors import err, ERR_INVALID_REQUEST
from helpers import get_json_body, require_fields
from middleware import authenticate, require_role
from response import success

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        clock.set(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 instant")
    # PRD endpoint output: null -> empty object in the data field (PRD 2.2).
    return success({}, status=200)
