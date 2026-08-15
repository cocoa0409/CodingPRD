"""Logical clock endpoint (PRD 2.5): free-setting, then the five sweeps."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.sweep import run_sweeps
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["FirmAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    run_sweeps()
    return success_object({"current_utc": CLOCK.now_iso()})
