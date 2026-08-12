"""Logical clock endpoint."""

from flask import Blueprint

import db
from middleware import authenticate, require_role
from response import success_object
from util import body_json, check_unknown_fields, require_fields, parse_dt, fmt_dt
from errors import raise_err, ERR_VALIDATION

bp = Blueprint("clock", __name__)


@bp.post("/sugarhouse/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_role(caller, {"SugarhouseManager"})
    data = body_json()
    check_unknown_fields(data, {"to_iso8601"})
    require_fields(data, ["to_iso8601"])
    try:
        dt = parse_dt(data["to_iso8601"])
    except Exception:
        raise_err(ERR_VALIDATION, "to_iso8601 must be a valid ISO8601 datetime")
    db.clock_iso = fmt_dt(dt)
    return success_object({"current_utc": db.clock_iso})
