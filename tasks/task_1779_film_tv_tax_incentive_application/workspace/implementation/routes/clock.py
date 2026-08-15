"""Test-driving logical clock endpoint (FilmOfficeAdmin only)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from util import CLOCK, parse_dt
from validate import get_body, reject_unknown_fields, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorized(["FilmOfficeAdmin"])
    body = get_body()
    reject_unknown_fields(body, {"to_iso8601"})
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        CLOCK.set(to_iso8601)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO-8601 instant")
    return success_object({"current_utc": CLOCK.now_iso()})
