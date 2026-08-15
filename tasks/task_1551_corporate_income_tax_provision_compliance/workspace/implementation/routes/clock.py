"""Test-driving endpoint (outside the business surface): advance the logical
clock and run the late/overdue/lapse sweeps synchronously (PRD §2.7)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from services.sweeps import run_sweeps
from util import CLOCK
from validate import body_json

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorized(("PlatformAdmin",))
    data = body_json()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 is required and must be a string")
    CLOCK.set(to_iso8601)  # raises ERR_INVALID_REQUEST on malformed input or regression
    late_ids, overdue_ids, lapsed_ids = run_sweeps(CLOCK.today())
    return success_object({
        "current_utc": CLOCK.now_iso(),
        "late_payment_ids": late_ids,
        "overdue_notice_ids": overdue_ids,
        "lapsed_position_ids": lapsed_ids,
    })
