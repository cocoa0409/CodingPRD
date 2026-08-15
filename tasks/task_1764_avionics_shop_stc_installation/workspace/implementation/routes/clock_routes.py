"""Logical clock test-driving endpoint (ShopManager only)."""
from flask import Blueprint

import clock
import middleware as mw
from middleware import authenticate, require_role, body, req_dt
from response import success
from util import iso_millis

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    to = req_dt(b, "to_iso8601")
    clock.set_now(to)
    return success({"current_utc": iso_millis(clock.now())}, 200)
