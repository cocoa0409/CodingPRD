"""Test-driving logical clock endpoint (PRD 2.6)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/ucp/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorized(["SystemAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    return success_object({"current_utc": CLOCK.now_iso()})
