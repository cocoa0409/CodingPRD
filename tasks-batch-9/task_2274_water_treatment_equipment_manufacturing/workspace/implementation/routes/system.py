"""Logical clock endpoint."""
from flask import Blueprint

import auth
import clock
import response
import validate

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require("PlatformAdmin")
    body = validate.body()
    now = validate.instant(body, "now", required=True)
    clock.set_now(now)
    return response.ok({"now": clock.now_iso()})
