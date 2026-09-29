"""Test-driving surface: the logical clock."""

from flask import Blueprint

import validate as v
from auth import authenticate
from db import iso, set_clock
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/dropship/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlatformAdmin",))
    body = v.payload()
    instant = v.req_datetime(body, "current_utc")
    set_clock(instant)
    return ok({"current_utc": iso(instant)})
