"""Logical clock endpoint (PRD 3.10). The only way time moves in the system."""
from flask import Blueprint

from errors import raise_error, ERR_VALIDATION
from middleware import authorized
from response import success_object
from util import CLOCK, parse_dt
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorized(["DualCreditAdmin"])
    to_iso8601 = req_str(get_body(), "to_iso8601")
    try:
        parse_dt(to_iso8601)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "to_iso8601 must be a valid ISO8601 UTC instant")
    CLOCK.set(to_iso8601)
    return success_object({"now_iso8601": CLOCK.now_iso()})
