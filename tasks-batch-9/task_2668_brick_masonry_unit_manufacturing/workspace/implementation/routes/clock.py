"""The administrative logical-clock capability (PRD 2.4)."""

import response
from auth import ALL_ROLES, endpoint
from store import set_clock
from validation import body, v_datetime

from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc():
    payload = body()
    instant = v_datetime(payload, "to_iso8601")
    set_clock(instant)
    return response.ok({"current_utc": payload["to_iso8601"]})
