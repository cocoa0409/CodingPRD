"""The logical clock (PRD 2.4)."""

from flask import Blueprint

from db import db
from middleware import auth, f_dt, get_body
from response import ok
from util import iso_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(("VenueAdmin",))
    body = get_body()
    _raw, parsed = f_dt(body, "to_iso8601")
    previous = iso_clock(db.clock)
    db.clock = parsed
    return ok({"current_utc": iso_clock(db.clock), "previous_utc": previous})
