"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import CLOCK, iso_logical
from middleware import ctx
from response import ok_object
from services import req_body, v_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx()  # any authenticated role
    b = req_body()
    _, dt = v_datetime(b, "to_iso8601")
    CLOCK["now"] = dt
    return ok_object({"current_utc": iso_logical(CLOCK["now"])})
