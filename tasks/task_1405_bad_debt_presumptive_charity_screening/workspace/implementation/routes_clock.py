"""Logical clock endpoint (PRD 2.4): set current UTC and run the
payment-plan default sweep and the dispute-expiry sweep."""

from flask import Blueprint

from db import db
from middleware import (
    ROLE_COLLECTOR,
    ROLE_COUNSELOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_object
from services import run_clock_sweeps
from util import get_body, iso_sec, parse_datetime_value, req_str

bp = Blueprint("clock", __name__)


@bp.post("/self-pay/_clock/set_current_utc")
def set_current_utc():
    authenticate([ROLE_COLLECTOR, ROLE_COUNSELOR, ROLE_OFFICER])
    b = get_body()
    to_iso8601 = req_str(b, "to_iso8601")
    db.now = parse_datetime_value(to_iso8601)
    plans_flagged, disputes_expired = run_clock_sweeps()
    return ok_object({
        "now_iso8601": iso_sec(db.now),
        "plans_flagged_in_default": plans_flagged,
        "disputes_expired": disputes_expired,
    })
