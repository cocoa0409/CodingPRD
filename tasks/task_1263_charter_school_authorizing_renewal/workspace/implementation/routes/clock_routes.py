"""Logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

import errors
from clock import CLOCK, to_iso
from errors import raise_error
from middleware import body, require_non_empty_string, require_roles
from response import success_object

bp = Blueprint("clock_routes", __name__)


@bp.post("/authorizer/_clock/set_current_utc")
def set_current_utc():
    require_roles(["AuthorizerAdmin"])
    data = body()
    to_iso8601 = require_non_empty_string(data, "to_iso8601")
    try:
        new_now = CLOCK.set(to_iso8601)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp")
    return success_object({"current_utc": to_iso(new_now)})
