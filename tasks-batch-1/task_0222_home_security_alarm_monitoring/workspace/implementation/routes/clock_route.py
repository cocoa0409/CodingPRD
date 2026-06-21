"""Test-driving logical clock endpoint."""
from flask import Blueprint

import clock
from errors import err, ERR_VALIDATION
from middleware import authenticate, require_role
from response import success
from services import validate

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()
    now_utc = validate.require_str(body, "now_utc")
    try:
        dt = clock.parse_ts(now_utc)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "now_utc is not a valid ISO 8601 timestamp")
    clock.set_now(dt)
    return success({})
