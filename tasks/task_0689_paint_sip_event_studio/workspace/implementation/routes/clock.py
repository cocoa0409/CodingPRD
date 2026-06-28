"""Logical clock control (PRD §3.12). PlatformAdmin only."""
from flask import Blueprint

import errors
import helpers
import middleware
from clock import clock
from errors import err
from helpers import iso_from_dt
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    middleware.authenticate()
    middleware.require_roles("PlatformAdmin")
    body = helpers.get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(errors.ERR_VALIDATION, "Missing required field: to_iso8601")
    dt = helpers._parse_iso(body["to_iso8601"], "to_iso8601")
    clock.set(dt)
    return object_response({"now_utc": iso_from_dt(clock.now())}, 200)
