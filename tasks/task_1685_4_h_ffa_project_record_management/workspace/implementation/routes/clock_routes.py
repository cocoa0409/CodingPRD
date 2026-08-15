"""POST /api/_clock/set_current_utc -- ProgramAdmin-only test-driving endpoint
for the program-year logical clock (PRD 2.5)."""

from flask import Blueprint

import clock
import response
from middleware import authenticate, resolve_caller
from validation import get_body, as_datetime_str
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role, user_id = authenticate(["ProgramAdmin"])
    resolve_caller(role, user_id)  # ProgramAdmin: opaque, no entity resolution
    body = get_body()
    raw = as_datetime_str(body, "to_iso8601")
    dt = clock.parse_iso(raw)
    if dt is None:  # defensive; as_datetime_str already enforces
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'to_iso8601': must be an ISO 8601 UTC timestamp")
    clock.set_current(dt, raw)
    return response.success({"current_utc": clock.current_raw()}, status=200)
