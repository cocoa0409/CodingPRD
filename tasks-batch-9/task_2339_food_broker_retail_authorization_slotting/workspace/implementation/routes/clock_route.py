"""The logical-clock test capability (PRD section 2.5)."""

from flask import Blueprint

import clock
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(*ALL_ROLES)
    data = v.body()
    raw = v.req(data, "current_utc")
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'current_utc' must be a string.")
    parsed = clock.parse_instant(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'current_utc' must be an ISO 8601 UTC instant.")
    clock.set_now(parsed)
    return response.ok({"current_utc": raw})
