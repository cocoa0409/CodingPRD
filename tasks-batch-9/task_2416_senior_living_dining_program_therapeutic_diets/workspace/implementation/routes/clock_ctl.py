"""Test-driving endpoint for the logical clock (PRD 2.5)."""
from flask import Blueprint

from auth import authenticate
from clock import clock
from response import ok
from routes.common import PA
from shape import body_json, req_instant

bp = Blueprint("clock_ctl", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([PA])
    body = body_json()
    instant = req_instant(body, "current_utc")
    clock.set(instant)
    # The supplied representation is echoed back verbatim.
    return ok({"current_utc": body["current_utc"]})
