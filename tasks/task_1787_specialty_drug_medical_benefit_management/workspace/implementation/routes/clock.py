"""Logical clock endpoint (PRD 2.4): PlanAdmin-only test-driving capability.

Setting the clock eagerly applies every due transition; the same transitions
are also applied lazily in a before_request sweep.
"""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from routes.helpers import get_body, req_str
from services.sweep import run_sweep
from util import CLOCK, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    authorized(["PlanAdmin"])
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        new_dt = parse_dt(to_iso8601)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC instant")
    if new_dt < CLOCK.now():
        raise_error(ERR_INVALID_REQUEST, "the logical clock only advances forward")
    CLOCK.set(new_dt)
    run_sweep()
    return success_object({})
