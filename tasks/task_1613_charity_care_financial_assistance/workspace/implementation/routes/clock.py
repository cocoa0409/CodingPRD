"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from util import CLOCK, is_valid_datetime
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.post("/charity-care/_clock/set_current_utc")
def set_current_utc():
    authorized(["ComplianceOfficer"])
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    if not is_valid_datetime(to_iso):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    CLOCK.set(to_iso)
    return success_object({"current_utc": CLOCK.now_iso()})
