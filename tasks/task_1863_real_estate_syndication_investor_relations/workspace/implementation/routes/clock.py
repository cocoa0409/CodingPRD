"""Logical-clock test-driving endpoint (PRD 2.8)."""
from flask import Blueprint

from middleware import SPONSOR, endpoint
from response import success_object
from services.domain import sweep_defaults
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)
RS = {"strict_slashes": False}


@bp.route("/_clock/set_current_utc", methods=["POST"], **RS)
@endpoint(SPONSOR)
def set_current_utc(caller):
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    # Eagerly materialize lazy state transitions (e.g. past-due contributions).
    sweep_defaults()
    return success_object({"current_utc": CLOCK.now_iso()})
