"""Logical clock test-driving endpoint (PRD 2.5)."""

from flask import Blueprint

import clock
import middleware as mw
import response
from services import workflows as wf

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    mw.require_auth(["GalaAdmin"])
    body = mw.get_json_body()
    to = mw.require_datetime(body, "to_iso8601")
    clock.set_current(to)
    # Setting the clock runs the certificate expiry sweep (strict > expires_at).
    wf.expiry_sweep()
    return response.success_object({"current_utc": clock.fmt(clock.now())})
