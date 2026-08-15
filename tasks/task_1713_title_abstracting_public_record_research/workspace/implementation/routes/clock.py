"""Logical clock test-driving endpoint."""

import db
from middleware import authenticate
from response import success_obj
from routes import make_blueprint
from util import body_json, check_shape, parse_dt

bp = make_blueprint("clock")

_SET_SPEC = {
    "to_iso8601": {"type": "datetime", "required": True},
}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _SET_SPEC)
    db.set_clock(parse_dt(body["to_iso8601"], "to_iso8601"))
    # is_overdue is derived at read time, so setting the clock re-evaluates
    # it on every non-terminal order with no further writes.
    return success_obj({"current_utc": body["to_iso8601"]}, 200)
