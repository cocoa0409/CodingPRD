"""Logical clock (PRD 2.4): admin-only test-driving capability."""

from flask import Blueprint

import db
from middleware import authenticate
from response import success_obj
from util import body_json, check_shape, parse_dt

bp = Blueprint("clock", __name__, url_prefix="/port-ops")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _user_id, _role = authenticate({"PortAuthorityAdmin"})
    body = body_json()
    check_shape(body, {"to_iso8601": {"type": "datetime", "required": True}})
    db.set_clock(parse_dt(body["to_iso8601"], "to_iso8601"))
    return success_obj({"current_utc": db.fmt_ts(db.now())})
