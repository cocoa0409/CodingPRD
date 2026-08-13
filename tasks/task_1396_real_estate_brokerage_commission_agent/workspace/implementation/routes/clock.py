"""POST /brokerage/_clock/set_current_utc — the logical clock (PRD §2.4)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_CLOCK_REGRESSION
from middleware import body, req_str
from response import success_obj
from routes.helpers import guard
from timeutil import parse_iso8601, iso_ts_ms

bp = Blueprint("clock", __name__)


@bp.route("/brokerage/_clock/set_current_utc", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def set_clock(user_id, role):
    data = body()
    to_iso = req_str(data, "to_iso8601")
    try:
        target = parse_iso8601(to_iso)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO-8601 datetime")

    if not target > db.now():
        raise ApiError(ERR_CLOCK_REGRESSION, 422,
                       "the clock moves forward only")

    db.clock["now"] = target

    from services.anniversary import sweep_clock
    activated, closed = sweep_clock()

    return success_obj({
        "current_utc": iso_ts_ms(target),
        "activated_enrollment_ids": activated,
        "closed_window_ids": closed,
    })
