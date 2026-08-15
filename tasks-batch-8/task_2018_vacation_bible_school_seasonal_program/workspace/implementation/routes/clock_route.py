"""Logical clock test-driving endpoint (PRD §2.4)."""

from flask import Blueprint

import clock
from auth import authenticate, require_role
from envelope import ok_object
from util import fmt_dt
from validate import Field, get_body, validate_body

bp = Blueprint("clock", __name__)

_SET_SPEC = {
    "to_iso8601": Field("datetime", required=True),
}


@bp.post("/vbs/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    data = validate_body(body, _SET_SPEC)
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    current = clock.set_current(data["to_iso8601"])
    return ok_object({"current_utc": fmt_dt(current)})
