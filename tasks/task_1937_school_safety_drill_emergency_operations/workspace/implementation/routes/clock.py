"""Logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

from errors import raise_error, ERR_VALIDATION
from middleware import authorized, ROLE_COORDINATOR
from response import success_object
from services.sweep import run_sweep
from util import CLOCK, parse_dt
from validate import get_body, reject_unknown, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized([ROLE_COORDINATOR])
    body = get_body()
    reject_unknown(body, ["to_iso8601"])
    to_iso8601 = req_datetime(body, "to_iso8601")
    if parse_dt(to_iso8601) < CLOCK.now():
        raise_error(ERR_VALIDATION, "logical clock cannot move backwards")
    CLOCK.set(to_iso8601)
    run_sweep()
    return success_object({})
