"""The logical clock (PRD section 2.3)."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import WRITER_ROLES, authenticate
from response import ok
from validation import field_instant, get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(WRITER_ROLES)
    body = get_body()
    raw, moment = field_instant(body, "current_utc")
    if moment < db.clock:
        raise ApiError("ERR_CLOCK_REWIND",
                       "The logical clock may only move forward.")
    # Setting the clock changes no row and fires no cascade.
    db.clock = moment
    db.clock_raw = raw
    return ok({"current_utc": raw})
