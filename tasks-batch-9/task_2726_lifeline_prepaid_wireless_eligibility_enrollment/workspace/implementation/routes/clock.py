"""Test-only logical clock control (PRD 2.4). Seats an instant; writes no row."""
from flask import Blueprint

import db
import response
import validation as v
from routes.common import ROLES_ALL, authenticate

bp = Blueprint("clock", __name__)


@bp.post("/lifeline/_clock/set_current_utc")
def set_current_utc():
    authenticate(ROLES_ALL)
    body = v.get_body()
    instant = v.datetime_field(body, "to_iso8601")
    db.set_clock(instant)
    return response.ok({"current_utc": db.fmt_dt(db.now())})
