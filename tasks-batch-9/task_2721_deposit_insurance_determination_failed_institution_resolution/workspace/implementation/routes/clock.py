"""The logical clock (PRD sections 1 and 2.4).

The clock starts at 2026-08-01T00:00:00Z on every process start and is strictly
monotonic: setting it to exactly its current value is accepted and leaves it
unchanged, while any earlier instant is rejected.
"""

from flask import Blueprint

import response
import shape
from auth import ALL_ROLES, require
from db import db
from errors import ApiError
from util import format_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require(ALL_ROLES)
def set_current_utc():
    payload = shape.body()
    target = shape.req_datetime(payload, "to_iso8601")
    if target < db.clock:
        raise ApiError("ERR_CLOCK_MONOTONICITY")
    db.clock = target
    return response.ok({"current_utc": format_iso(db.clock)})
