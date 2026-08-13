"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import parse_iso_dt, store
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate, check_unknown, get_body
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["CertificationOfficer"])
    b = get_body()
    check_unknown(b, ["to_iso8601"])
    raw = b.get("to_iso8601")
    if not isinstance(raw, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be an ISO-8601 timestamp string")
    try:
        dt = parse_iso_dt(raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be an ISO-8601 timestamp string")
    # The logical clock never moves backward and never uses wall-clock time.
    if dt < store.clock_dt:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "The logical clock never moves backward")
    store.clock_dt = dt
    store.clock_str = raw
    return success_object({"current_utc": store.clock_str})
