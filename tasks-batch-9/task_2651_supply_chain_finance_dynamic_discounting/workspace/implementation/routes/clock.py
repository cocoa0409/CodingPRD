"""Logical clock endpoint (PRD 2.4, 3.5)."""

from flask import Blueprint

from middleware import PLATFORM_OPS, authenticate
from response import ok
from services import flows
from validation import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((PLATFORM_OPS,))
    b = body()
    _raw, instant = req_dt(b, "current_utc")
    flows.run_clock_sweep(instant)
    return ok({})
