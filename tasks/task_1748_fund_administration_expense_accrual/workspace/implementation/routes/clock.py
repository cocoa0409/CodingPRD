"""Test-driving logical clock endpoint. Strictly forward, all four roles."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import ok
from validation import parse_body, parse_iso_dt

bp = Blueprint("clock", __name__)

CLOCK_SCHEMA = {
    "to_iso8601": ("iso8601", True, None),
}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    get_context()
    require_roles(ALL_ROLES)
    body = parse_body(CLOCK_SCHEMA)
    target = parse_iso_dt(body["to_iso8601"])
    if target <= db.LOGICAL_CLOCK:
        raise ApiError("ERR_CLOCK_REGRESSION", 422,
                       "The logical clock moves strictly forward")
    db.set_clock(target)
    return ok({"current_utc": db.logical_now()})
