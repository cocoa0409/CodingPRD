"""Test-driving logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

from db import set_logical_clock, logical_now, iso_ms
from middleware import require_roles, body, req_dt
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/crating/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    d = body()
    to = req_dt(d, "to_iso8601")
    set_logical_clock(to)
    return success({"current_utc": iso_ms(logical_now())})
