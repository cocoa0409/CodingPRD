"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.core import run_sweep
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["PlatformAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    new_dt = CLOCK.set(to_iso8601)
    run_sweep(new_dt)
    return success_object({"current_utc": CLOCK.now_iso()})
