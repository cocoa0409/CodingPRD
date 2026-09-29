"""The logical clock and the daily close (PRD Section 2.5)."""

from flask import Blueprint

import validators as v
from db import db
from errors import bad_request
from middleware import endpoint
from response import empty_response
from services.close import run_daily_close

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("PortfolioAdmin")
def set_clock():
    body = v.json_body()
    target, _raw = v.get_instant(body, "to_iso8601")
    # The clock is forward-only; it never falls back to wall-clock time.
    if target < db.clock:
        raise bad_request(
            "Field 'to_iso8601' may not be earlier than the current logical clock."
        )
    db.clock = target
    return empty_response()


@bp.post("/_ops/run-daily-close")
@endpoint("PortfolioAdmin")
def run_close():
    # The close takes no input beyond the acting role.
    v.json_body()
    run_daily_close()
    return empty_response()
