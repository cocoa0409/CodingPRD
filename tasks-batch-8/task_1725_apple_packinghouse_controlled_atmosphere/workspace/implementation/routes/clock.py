"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["Admin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)  # backwards settings raise ERR_INVALID_REQUEST
    return success_object({})
