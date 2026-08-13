"""Test-driving logical clock (PRD §2.4)."""
from flask import Blueprint

import auth
import db
import errors
import util

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    body = util.get_body(required=True)
    util.req_fields(body, ["to_iso8601"])
    dt = db.set_clock(body["to_iso8601"])
    if dt is None:
        raise errors.validation("to_iso8601 is unparseable")
    return util.ok({"current_utc": db.fmt_dt(dt)})
