"""Test-driving logical clock (DeiAdmin only). Setting the clock runs the
term-expiry sweep and the leadership-gap cascade."""
from flask import Blueprint

from db import set_clock
from middleware import authenticate, body, req_dt
from services import term_expiry_sweep
from util import ok_object

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_current_utc():
    authenticate(("DeiAdmin",))
    data = body()
    to = req_dt(data, "to_iso8601")
    set_clock(to)
    term_expiry_sweep(to)
    return ok_object({})
