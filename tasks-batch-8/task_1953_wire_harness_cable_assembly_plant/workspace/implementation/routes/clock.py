"""Logical clock test-driving endpoint (PRD 2.5)."""
from flask import Blueprint

from middleware import authenticate
from response import success_object
from util import CLOCK
from validate import get_body, req_dt

bp = Blueprint("clock", __name__)

QUALITY_MANAGER = {"QualityManager"}


@bp.route("/plant/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = get_body()
    req_dt(body, "to_iso8601")  # tier-1 parse check
    authenticate(QUALITY_MANAGER)
    CLOCK.set(body["to_iso8601"])
    return success_object({"current_utc": CLOCK.now_iso()}, 200)
