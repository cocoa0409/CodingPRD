"""The test-driving logical clock (PRD 2.4)."""

from flask import Blueprint

import validation as v
from db import set_clock
from middleware import authenticate
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlatformAdmin",))
    body = v.json_body()
    instant = v.req_datetime(body, "to_iso8601")
    # No entity is mutated: only the server's logical instant moves.
    set_clock(instant)
    return ok(None)
