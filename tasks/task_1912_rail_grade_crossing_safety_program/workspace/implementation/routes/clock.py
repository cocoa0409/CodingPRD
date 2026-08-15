"""Test-driving logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import body_or_empty, parse_instant, reject_unknown
from middleware import auth
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["ProgramAdministrator"])
    body = body_or_empty()
    reject_unknown(body, ("to_iso8601",))
    raw = body.get("to_iso8601")
    parsed = parse_instant(raw)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'to_iso8601' is required and must be an ISO 8601 UTC timestamp")
    store.clock = parsed
    store.clock_raw = raw
    return ok({"current_utc": store.clock_raw})
