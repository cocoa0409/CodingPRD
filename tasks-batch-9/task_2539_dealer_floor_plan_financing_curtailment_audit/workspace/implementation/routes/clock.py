"""The clock-control route: test infrastructure outside the business namespace."""

from flask import Blueprint

import db
import middleware
import response
import validate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require(middleware.SYSTEM_OPERATOR)
    data = validate.body()
    moment = validate.req_instant(data, "to_iso8601")
    previous = db.CLOCK.set(moment)
    return response.ok(
        {
            "current_utc": db.fmt_instant(db.now()),
            "previous_utc": db.fmt_instant(previous),
        }
    )
