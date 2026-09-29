"""POST /drive-thru/_clock/set_current_utc"""

from flask import Blueprint

from db import db, fmt_dt
from errors import fail
from middleware import authenticate
from response import ok
from services.rollup import recompute_all
from validation import body_or_400, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(("ProgramAdmin",))
    body = body_or_400()
    target = req_dt(body, "to_iso8601")

    if target < db.clock:
        fail("ERR_CLOCK_REGRESSION", "the logical clock may not move backwards")

    db.clock = target
    recompute_all()
    return ok({"current_utc": fmt_dt(db.clock)})
