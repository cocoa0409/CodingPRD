"""The server logical clock (PRD section 2.4)."""

from flask import Blueprint

from db import db
from middleware import CAPITAL_PLANNER, guard
from response import object_response
from validation import body, dt_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(CAPITAL_PLANNER)
def set_current_utc():
    data = body()
    raw, parsed = dt_field(data, "now", required=True)
    db.clock = parsed
    db.clock_raw = raw
    return object_response({"now": raw})
