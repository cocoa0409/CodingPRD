"""Test-driving logical clock (PRD 2.5)."""
from flask import Blueprint

from errors import raise_error, ERR_VALIDATION
from helpers import get_body, req_field
from middleware import get_caller, check_role_allowed
from response import success_object
from util import CLOCK, parse_datetime

bp = Blueprint("clock", __name__)


@bp.route("/kitchen/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin"])

    to_iso8601 = req_field(body, "to_iso8601", str)
    try:
        CLOCK.set(to_iso8601)
    except ValueError:
        raise_error(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime")

    return success_object({"current_utc": CLOCK.now_iso()})
