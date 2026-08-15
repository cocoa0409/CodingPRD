"""Logical clock endpoint (test-driving)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import get_body, reject_server_managed, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/actuarial/_clock/set_current_utc")
def set_current_utc():
    authorized(["AppointedActuary"])
    body = get_body()
    reject_server_managed(body)
    to_iso = req_datetime(body, "to_iso8601")
    dt = CLOCK.set(to_iso)
    from util import fmt_datetime
    return success_object({"current_utc": fmt_datetime(dt)})
