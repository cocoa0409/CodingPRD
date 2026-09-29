"""The logical clock (PRD 2.4)."""

from flask import Blueprint

from auth import authenticate
from response import object_response
from store import set_clock
from validate import f_str, get_body, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate()
    body = get_body(("current_utc",))
    raw = f_str(body, "current_utc", required=True)
    set_clock(parse_dt(raw))
    # Mutates no business entity; the response echoes the supplied instant.
    return object_response({"current_utc": raw})
