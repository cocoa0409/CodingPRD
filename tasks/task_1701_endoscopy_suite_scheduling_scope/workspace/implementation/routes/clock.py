"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from errors import raise_error, ERR_CLOCK_REGRESSION
from middleware import authorized
from response import success_object
from util import CLOCK, render_instant
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/endoscopy/_clock/set_current_utc")
def set_clock():
    authorized(["UnitAdmin"])
    body = get_body()
    target = req_datetime(body, "to_iso8601")
    # Rung 9 (business_temporal): the target must be strictly later.
    if target <= CLOCK.now():
        raise_error(ERR_CLOCK_REGRESSION,
                    "to_iso8601 must be strictly later than the current logical time")
    CLOCK.set(target)
    return success_object({"current_utc": render_instant(CLOCK.now())})
