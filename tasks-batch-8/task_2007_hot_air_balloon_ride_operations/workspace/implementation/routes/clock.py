"""Logical clock test-driving endpoint (PRD 2.5)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK, fmt_datetime
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__, url_prefix="/v1")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["OperationsManager"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    new_dt = CLOCK.set(to_iso8601)
    return success_object({"current_utc": fmt_datetime(new_dt)})
