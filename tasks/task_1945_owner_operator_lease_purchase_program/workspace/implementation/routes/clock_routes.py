"""Test-driving logical clock endpoint."""

from flask import Blueprint

import clock
import middleware
from response import success
from util import get_body, req_dt

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    to = req_dt(body, "to_iso8601")
    clock.set_current(to)
    return success({"current_utc": clock.iso(clock.now())}, "object", 200)
