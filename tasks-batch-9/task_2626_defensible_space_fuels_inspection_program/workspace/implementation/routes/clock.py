"""The logical clock control surface (PRD section 2.5).

Setting the clock may move it forward or backward and performs no state
transitions of its own; time-driven consequences land only at a cycle advance.
"""

from flask import Blueprint

from auth import auth
from db import db
from response import ok
from validate import body, get_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth("ProgramAdmin")
    b = body()
    moment = get_dt(b, "to_iso8601")
    db.clock = moment
    return ok({"current_utc": moment})
