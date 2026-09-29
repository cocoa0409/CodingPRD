"""The logical clock. Every temporal rule in the system reads this value; the
host wall clock is never consulted."""

from flask import Blueprint

import db
import response
import validators as v
from middleware import authenticate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate()
    body = v.body()
    text, moment = v.ts_field(body, "to_iso8601")
    db.db.clock = moment
    return response.ok({"current_utc": db.iso(moment)})
