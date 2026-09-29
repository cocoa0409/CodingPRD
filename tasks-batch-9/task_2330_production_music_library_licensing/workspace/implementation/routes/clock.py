"""POST /_clock/set_current_utc — the only endpoint outside the api prefix."""

from flask import Blueprint

from errors import fail
from middleware import ALL_STAFF, body, req_datetime, require_role
from response import object_response
from services.cascade import clock_advance
from db import DB

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body()
    _raw, target = req_datetime(data, "to_iso8601")          # 1 schema
    require_role(*ALL_STAFF)                                 # 4 role
    if target < DB.now:
        fail("ERR_CLOCK_REWIND", "The logical clock only moves forward.")
    return object_response(clock_advance(target))
