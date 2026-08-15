"""Logical clock test-driving endpoint (PRD 2.4)."""

import db
from middleware import authenticate
from response import success_obj
from routes import make_blueprint
from util import body_json, check_shape, parse_dt

bp = make_blueprint("clock")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["ProcurementAdmin"])
    body = body_json()
    check_shape(body, {"to_iso8601": {"type": "datetime", "required": True}})
    db.set_clock(parse_dt(body["to_iso8601"], "to_iso8601"))
    return success_obj({"current_utc": body["to_iso8601"]}, 200)
