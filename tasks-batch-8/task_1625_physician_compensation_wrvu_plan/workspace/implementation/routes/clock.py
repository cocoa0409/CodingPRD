"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from errors import raise_error, ERR_VALIDATION
from middleware import authorized
from response import success_object
from util import CLOCK, is_valid_iso_datetime
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["SystemAdmin"])
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    if not is_valid_iso_datetime(to_iso8601):
        raise_error(ERR_VALIDATION, "to_iso8601 must be a well-formed ISO 8601 timestamp")
    CLOCK.set(to_iso8601)
    # Side effect (recompute every EFFECTIVE agreement's compliance_hold) is
    # automatic: compliance_hold is derived live from the clock on every read.
    return success_object({"current_utc": CLOCK.now_iso()})
